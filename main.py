from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pathlib import Path
import json
import time

app = FastAPI()

# =========================
# 1) 질문/답변(캐시) 데이터
# =========================
# qid -> 고정 답변 텍스트 (논문 실험용 통제)
ANSWERS = {
    # Cause (3)
    "cause_1": """현재까지의 조사 결과에 따르면 이번 사고는 외부 접근 경로를 통해 일부 고객 정보에 대한 무단 접근으로 발생하였습니다. 
    
정확한 접근 방식과 경위에 대해서는 추가적인 분석이 진행 중입니다.""",
    "cause_2": """현재까지 확인된 바에 따르면 해당 접근은 8월 24일경부터 일정 기간 동안 발생한 것으로 파악되고 있습니다. 
    
정확한 시점과 지속 기간은 추가 확인 중입니다.""",
    "cause_3": """무단 접근이 확인된 정보는 이름, 이메일 주소, 전화번호, 배송지 주소, 그리고 일부 주문 정보입니다. 
    
비밀번호, 결제 정보, 신용카드 정보 등의 핵심적인 금융 정보는 포함되지 않았습니다.""",

    # Response (3)
    "response_1": "사고 인지 이후 해당 보안 시스템에 대해서는 접근 제한 조치가 적용되었습니다. 또한 추가적인 정보 노출을 방지하기 위한 점검이 진행되고 있습니다.",
    "response_2": "현재 해당 서비스의 주요 기능은 정상적으로 운영되고 있으며, 추가적인 이상 여부를 확인하기 위한 모니터링이 지속되고 있습니다.",
    "response_3": "사건의 수습 및 추후 처리를 위해 현재 관련 당국과 협력해 사고 원인과 영향을 분석하는 절차가 진행 중입니다.",

    # Remedy (3)
    "remedy_1": "현재 발생한 개인정보 유출 사고에 대응해 사용자에게는 계정 보안 강화를 위한 비밀번호 변경 및 보안 설정 점검이 안내되고 있습니다.",
    "remedy_2": "이번 사고와 관련해 개인적인 문의 사항이나 추가 확인이 필요하신 경우, 고객 지원 채널을 통해 문의를 접수하실 수 있습니다.",
    "remedy_3": """현재 개별 사용자의 개인 정보 유출을 확인할 수 있는 서비스가 운영되고 있습니다.
    
개인정보 유출 피해를 입으신 고객님들에 대한 추가적인 안내는 공식 공지 채널을 통해 제공될 예정입니다.""",

    # Prevention & Future Plan (3)
    "plan_1": """향후 유사한 사고를 방지하기 위해 회사에서는 해당 보안 시스템에 대한 접근 제어 절차 및 보안 점검 체계에 대한 검토를 예정하고 있습니다. 또한 현재 해당 시스템 외에도 기존의 보안 시스템에 대한 점검이 진행되고 있습니다. 
    
관련 개선 사항은 검토 및 개선 계획이 수립되는대로 안내될 예정입니다.""",
    "plan_2": "조사 및 점검 절차의 진행 상황에 따라 주요 업데이트는 공식 공지 채널을 통해 공유될 예정입니다.",
    "plan_3": "관련 절차가 마무리될 때까지 추가로 확인되는 사항은 공식 채널을 통해 순차적으로 안내될 예정입니다.",
}

# UI에 보여줄 질문 라벨(프론트용)
QUESTIONS = {
    "Cause": [
        ("cause_1", "사고 발생 경위"),
        ("cause_2", "발생 시점"),
        ("cause_3", "영향 범위"),
    ],
    "Response": [
        ("response_1", "사고 이후 조치"),
        ("response_2", "현재 운영 상태"),
        ("response_3", "정부/외부기관과의 협력"),
    ],
    "Remedy": [
        ("remedy_1", "사용자 권장 행동"),
        ("remedy_2", "개별 문의"),
        ("remedy_3", "피해 여부 확인"),
    ],
    "Prevention & Future Plan": [
        ("plan_1", "재발 방지 조치"),
        ("plan_2", "추가 업데이트"),
        ("plan_3", "사고 수습 예상 완료 시점"),
    ],
}

# =========================
# 2) 로그 저장(JSONL)
# =========================
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "events.jsonl"

def log_event(event: dict):
    """한 줄 JSON으로 계속 append (논문용 로그)."""
    event.setdefault("ts", time.time())
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# =========================
# 3) 단일 페이지 UI (모달 채팅)
# =========================
HTML = f"""
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>AI Spokesperson Stimulus (Controlled)</title>
  <style>
    :root {{
      --bg: #f6f7fb;
      --modal: #ffffff;
      --line: #e6e8ef;
      --text: #1f2430;
      --muted: #6b7280;
      --chip: #f1f2f6;
      --chip-on: #e9e6ff;
      --accent: #d67aa5;
      --shadow: 0 10px 35px rgba(0,0,0,.18);
      --radius: 16px;
    }}
    html, body {{ height: 100%; }}
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, "Noto Sans KR", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}

    /* Page mock (behind modal) */
    .page {{
      padding: 28px;
      opacity: .35;
      filter: blur(0px);
    }}
    .topbar {{
      display:flex; justify-content:space-between; align-items:center;
      padding: 12px 16px; background:#fff; border:1px solid var(--line); border-radius: 12px;
    }}
    .brand {{ font-weight: 700; }}
    .nav {{ display:flex; gap:14px; color: var(--muted); }}
    .btn {{
      background: #fff; border:1px solid var(--line); padding: 10px 12px; border-radius: 10px;
    }}

    /* Modal */
    .overlay {{
      position: fixed; inset: 0;
      background: rgba(0,0,0,.35);
      display:flex; align-items:center; justify-content:center;
      padding: 18px;
    }}
    .modal {{
      width: min(980px, 96vw);
      height: min(640px, 86vh);
      background: var(--modal);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      display:flex; flex-direction:column;
      overflow:hidden;
      border: 1px solid rgba(255,255,255,.4);
    }}
    .modal-header {{
      display:flex; align-items:center; justify-content:space-between;
      padding: 14px 18px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }}
    .status {{
      display:flex; align-items:center; gap:10px;
      font-weight: 600;
    }}
    .dot {{
      width: 10px; height: 10px; border-radius: 50%;
      background: #2ecc71;
      box-shadow: 0 0 0 4px rgba(46,204,113,.18);
    }}
    .close {{
      border:none; background:transparent; font-size: 22px; cursor:pointer;
      color: var(--muted);
      line-height: 1;
    }}

    /* ✅ FIX: grid -> flex column + min-height:0 */
    .modal-body {{
      flex: 1;
      display: flex;
      flex-direction: column;
      background: linear-gradient(180deg, #fff 0%, #fafbff 100%);
      min-height: 0; /* 핵심: 자식 overflow가 정상작동 */
    }}

    .agent {{
      display:flex; flex-direction:column; align-items:center;
      padding: 18px 18px 0 18px;
      gap: 8px;
      flex: 0 0 auto;
    }}
    .avatar {{
      width: 92px; height: 92px; border-radius: 50%;
      display:grid; place-items:center;
      background: radial-gradient(circle at 30% 30%, #ffe6f2, #fff);
      border: 2px solid #f3f4f7;
      box-shadow: 0 12px 25px rgba(0,0,0,.12);
      overflow:hidden;
    }}
    .avatar img {{
      width: 82px; height: 82px; object-fit: cover;
    }}
    .agent-name {{
      font-weight: 700;
      color: var(--accent);
    }}

    /* ✅ FIX: chat만 스크롤 */
    .chat {{
      flex: 1;
      min-height: 0;   /* 핵심 */
      padding: 12px 18px 10px 18px;
      overflow: auto;  /* 채팅만 스크롤 */
    }}
    .bubble-row {{
      display:flex; gap:10px; margin: 10px 0;
      align-items:flex-end;
    }}
    .bubble-row.user {{ justify-content:flex-end; }}
    .bubble {{
      max-width: 76%;
      padding: 12px 14px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: #fff;
      white-space: pre-wrap;
      line-height: 1.35;
      font-size: 15px;
    }}
    .bubble.ai {{
      background: #ffffff;
    }}
    .bubble.user {{
      background: #fff0f6;
      border-color: #ffd0e2;
    }}
    .meta {{
      font-size: 12px;
      color: var(--muted);
      margin: 0 2px 2px 2px;
    }}

    /* ✅ FIX: 하단 고정 영역(sticky) */
    .bottom-area {{
      position: sticky;
      bottom: 0;
      background: #fff;
      border-top: 1px solid var(--line);
      flex: 0 0 auto;
    }}

    .chips {{
      padding: 10px 18px 6px 18px;
      background: #fff;
      display:flex;
      flex-wrap:wrap;
      gap: 8px;
    }}
    .chip {{
      border: 1px solid var(--line);
      background: var(--chip);
      padding: 8px 10px;
      border-radius: 999px;
      cursor:pointer;
      font-size: 13px;
      user-select:none;
    }}
    .chip.active {{
      background: var(--chip-on);
      border-color: #d8d2ff;
    }}

    .composer {{
      padding: 10px 18px 12px 18px;
      background:#fff;
      display:flex; gap:10px;
      align-items:center;
      border-top: 0;
    }}
    .input {{
      flex:1;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px 12px;
      color: var(--muted);
      background: #fafafa;
    }}
    .send {{
      border:none;
      background: var(--accent);
      color:#fff;
      padding: 11px 14px;
      border-radius: 12px;
      font-weight: 700;
      opacity: .55;
      cursor:not-allowed;
    }}
    .hint {{
      font-size: 12px;
      color: var(--muted);
      padding: 0 18px 12px 18px;
      background:#fff;
    }}    
/* Priming screen */
.priming-wrap {{
  min-height: 100vh;
  display:flex;
  align-items:center;
  justify-content:center;
  padding: 22px;
}}
.priming-card {{
  width: min(980px, 96vw);
  background: #fff;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow:hidden;
}}
.priming-top {{
  padding: 18px;
  border-bottom: 1px solid var(--line);
  background: #fff;
}}
.news-img{{
  border-radius: 14px;
  border: 1px solid var(--line);
  background: linear-gradient(180deg, #ffffff 0%, #fafafa 100%);
  padding: 18px;
}}
.news-headline{{
  font-weight: 800;
  font-size: 18px;
  line-height: 1.25;
  margin-bottom: 8px;
  color: #111827;
}}
.news-sub{{
  font-size: 13px;
  color: var(--muted);
  line-height: 1.4;
}}
.priming-mid{{
  padding: 18px;
}}
.priming-title{{
  font-weight: 800;
  margin-bottom: 10px;
}}
.priming-bullets{{
  margin: 0;
  padding-left: 18px;
  color: #111827;
  line-height: 1.55;
}}
.priming-bullets li{{
  margin: 8px 0;
}}
.priming-bottom{{
  padding: 18px;
  border-top: 1px solid var(--line);
  background: #fff;
  display:flex;
  flex-direction:column;
  gap: 10px;
  align-items:flex-start;
}}
.priming-cta{{
  border: none;
  background: var(--accent);
  color: #fff;
  font-weight: 800;
  padding: 12px 14px;
  border-radius: 12px;
  cursor: pointer;
}}
.priming-note{{
  font-size: 12px;
  color: var(--muted);
}}  
  </style>
</head>
<body>
  <div class="page">
    <div class="topbar">
      <div class="brand">Aurelle Beauty</div>
      <div class="nav">
        <div>Home</div><div>Products</div><div>Chat</div>
      </div>
      <button class="btn">Contact Sales</button>
    </div>
  </div>

    <!-- Context Priming Screen -->
  <div class="priming-wrap" id="priming">
    <div class="priming-card">
      <div class="priming-top">
        <div class="news-img" aria-label="뉴스 기사 이미지 자리">
          <div class="news-headline">[속보] AI 보안 시스템 운영 대형 커머스 기업, 개인정보 유출 정황</div>
          <div class="news-sub">외부 접근으로 고객 정보 노출… 기업 “경위 조사 중”</div>
        </div>
      </div>

      <div class="priming-mid">
        <div class="priming-title">📌 사건 요약</div>
        <ul class="priming-bullets">
          <li>당신은 방금 개인정보 유출 관련 안내를 받았습니다.</li>
          <li>안내에 포함된 유출 여부 확인 페이지에서 조회한 결과, 당신의 계정 정보가 이번 사고의 영향 범위에 포함된 것으로 표시되었습니다.</li>
          <li><b>유출이 확인된 정보:</b> 이름, 이메일 주소, 전화번호, 배송지 주소, 일부 주문 정보</li>
          <li><b>유출되지 않은 정보:</b> 계정 비밀번호, 결제 정보, 신용카드 정보</li>
        </ul>
      </div>

      <div class="priming-bottom">
        <button class="priming-cta" id="startChatBtn">AI 대변인의 공식 대응 확인하기</button>
        <div class="priming-note">※ 다음 단계부터는 사전에 정의된 질문 버튼으로만 진행됩니다.</div>
      </div>
    </div>
  </div>
  
  <div class="overlay" id="overlay" style="display:none">
    <div class="modal">
      <div class="modal-header">
        <div class="status"><span class="dot"></span><span>Online</span></div>
        <button class="close" id="closeBtn" aria-label="close">×</button>
      </div>

      <div class="modal-body">
        <div class="agent">
          <div class="avatar" title="AI Spokesperson">
            <!-- 필요하면 여기 이미지 바꾸기 -->
            <img src="https://i.imgur.com/0y0y0y0.png" onerror="this.style.display='none'" alt="" />
          </div>
          <div class="agent-name" id="agentName">Elin</div>
        </div>

        <div class="chat" id="chat"></div>

        <!-- ✅ FIX: chips + composer + hint 를 bottom-area로 묶어서 항상 아래에 고정 -->
        <div class="bottom-area">
          <div class="chips" id="chips"></div>

          <div class="composer">
            <div class="input">자유 입력은 비활성화되어 있습니다. 아래 질문 버튼을 선택해 주세요.</div>
            <button class="send">Send</button>
          </div>

          <div class="hint">※ 실험 통제를 위해 질문은 미리 정의된 선택지로만 진행됩니다.</div>
        </div>
      </div>
    </div>
  </div>

<script>
  // -------------------------
  // 1) 세션(개인 대화) 만들기
  // -------------------------
  // 각 탭/브라우저마다 개인 세션이 되게 sessionStorage 사용
  function uuidv4() {{
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {{
      const r = Math.random() * 16 | 0, v = c === "x" ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    }});
  }}
  let sid = sessionStorage.getItem("sid");
  if(!sid) {{
    sid = uuidv4();
    sessionStorage.setItem("sid", sid);
  }}

  const chat = document.getElementById("chat");
  const chips = document.getElementById("chips");

  const QUESTIONS = {json.dumps(QUESTIONS, ensure_ascii=False)};

  function addBubble(role, text) {{
    const row = document.createElement("div");
    row.className = "bubble-row " + (role === "USER" ? "user" : "ai");

    const bubble = document.createElement("div");
    bubble.className = "bubble " + (role === "USER" ? "user" : "ai");
    bubble.textContent = text;

    row.appendChild(bubble);
    chat.appendChild(row);
    chat.scrollTop = chat.scrollHeight;
  }}

  // -------------------------
  // 2) 칩(질문 선택지) 렌더
  // -------------------------
  let activeCategory = null;

  function renderCategories() {{
    chips.innerHTML = "";
    Object.keys(QUESTIONS).forEach(cat => {{
      const c = document.createElement("div");
      c.className = "chip" + (cat === activeCategory ? " active" : "");
      c.textContent = cat;
      c.onclick = () => {{
        activeCategory = cat;
        renderCategories();
        renderQuestions(cat);
      }};
      chips.appendChild(c);
    }});
  }}

  function renderQuestions(cat) {{
    chips.innerHTML = "";

    const back = document.createElement("div");
    back.className = "chip";
    back.textContent = "← categories";
    back.onclick = () => {{
      activeCategory = null;
      renderCategories();
    }};
    chips.appendChild(back);

    QUESTIONS[cat].forEach(([qid, label]) => {{
      const q = document.createElement("div");
      q.className = "chip active";
      q.textContent = label;
      q.onclick = () => {{
        addBubble("USER", label);
        wsSend({{ type: "question", sid, qid, label }});
      }};
      chips.appendChild(q);
    }});
  }}

  // 초기엔 카테고리 칩 보여주기
  renderCategories();

  // -------------------------
  // 3) WebSocket 연결(개인용)
  // -------------------------
  const wsProto = (location.protocol === "https:") ? "wss" : "ws";
  const ws = new WebSocket(`${{wsProto}}://${{location.host}}/ws?sid=${{encodeURIComponent(sid)}}`);

  function wsSend(obj) {{
    if(ws.readyState === 1) ws.send(JSON.stringify(obj));
  }}

  ws.onopen = () => {{
    wsSend({{ type: "hello", sid }});
  }};

  ws.onmessage = (ev) => {{
    try {{
      const msg = JSON.parse(ev.data);
      if(msg.type === "ai") {{
        addBubble("AI", msg.text);
      }}
    }} catch {{
      // ignore
    }}
  }};

  ws.onerror = () => {{
    addBubble("AI", "[연결 오류] 네트워크 상태를 확인해 주세요.");
  }};

  ws.onclose = () => {{
    addBubble("AI", "[연결 종료] 새로고침하면 다시 연결됩니다.");
  }};

  // =========================
  // Context Priming → Chat 전환
  // =========================
  const priming = document.getElementById("priming");
  const overlay = document.getElementById("overlay");
  const startChatBtn = document.getElementById("startChatBtn");

  startChatBtn.onclick = () => {{
    priming.style.display = "none";
    overlay.style.display = "flex";
    chat.scrollTop = chat.scrollHeight;
  }};
</script>
</body>
</html>
"""


@app.get("/")
async def home():
    return HTMLResponse(HTML)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    # 각 접속은 "개인 세션" (브로드캐스트/방 없음)
    await ws.accept()

    # query param sid
    sid = None
    try:
        sid = ws.query_params.get("sid")
    except Exception:
        sid = None
    sid = (sid or "unknown")[:64]

    client_ip = ws.client.host if ws.client else None

    # 연결 로그
    log_event({"event": "connect", "sid": sid, "ip": client_ip})

    try:
        while True:
            raw = await ws.receive_text()
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"type": "unknown", "raw": raw}

            mtype = payload.get("type")

            if mtype == "hello":
                # 첫 턴: AI 대변인이 먼저 발화
                log_event({"event": "hello", "sid": sid})
                first_msg = (
                    "안녕하세요. 저는 본 사건에 대해 회사의 공식 입장을 전달하는 AI 대변인 ㅇㅇㅇ입니다. \n\n"
                    "먼저 이번 개인정보 유출 사고에 대해 사과드립니다. \n\n"
                    "저는 현재 확인된 사실과 회사의 대응 상황에 궁금하신 점을 안내드릴 예정입니다. \n아래에서 궁금하신 질문을 선택해주시면 그에 대한 정보를 안내드리겠습니다."
                )
                await ws.send_text(json.dumps({"type": "ai", "text": first_msg}, ensure_ascii=False))

            elif mtype == "question":
                qid = str(payload.get("qid", ""))[:64]
                label = str(payload.get("label", ""))[:200]

                # 로그
                log_event({"event": "question", "sid": sid, "qid": qid, "label": label})

                # 캐시 답변
                answer = ANSWERS.get(qid)
                if not answer:
                    answer = "해당 질문은 현재 실험 설계상 제공되지 않는 항목입니다. 다른 질문을 선택해 주세요."

                await ws.send_text(json.dumps({"type": "ai", "text": answer}, ensure_ascii=False))

            else:
                # 통제용: 자유 입력은 받지 않음 (로그만 남기고 안내)
                log_event({"event": "blocked_input", "sid": sid, "raw": str(payload)[:500]})
                await ws.send_text(json.dumps({
                    "type": "ai",
                    "text": "실험 통제를 위해 자유 입력은 비활성화되어 있습니다. 하단 질문 버튼을 선택해 주세요."
                }, ensure_ascii=False))

    except WebSocketDisconnect:
        log_event({"event": "disconnect", "sid": sid})
    except Exception as e:
        log_event({"event": "error", "sid": sid, "err": str(e)[:300]})
        try:
            await ws.close()
        except Exception:
            pass


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
