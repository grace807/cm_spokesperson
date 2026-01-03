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
    "cause_1": "사고 원인은 현재 1차 조사 결과, 외부 침해 시도가 내부 접근 통제의 취약점을 우회하면서 발생한 것으로 파악되고 있습니다. 다만 세부 경로는 포렌식이 진행 중이며, 확정 내용은 조사 완료 후 투명하게 공유하겠습니다. 지금은 사실로 확인된 범위만 말씀드리고, 추정은 배제하겠습니다.",
    "cause_2": "현재까지 확인된 바로는 단일 원인이라기보다, 접근 권한 관리 및 모니터링 체계에서 복합적인 취약점이 작동했을 가능성이 큽니다. 내부 규정 준수 여부와 운영 프로세스의 허점도 함께 점검하고 있습니다. 확정된 근거가 나오면 단계별로 공개하겠습니다.",
    "cause_3": "외부 공격 가능성은 높게 보고 있으며, 침해 지표(IOC) 기반으로 공격 벡터를 추적 중입니다. 동시에 내부 계정 오남용 가능성도 배제하지 않고 병행 조사하고 있습니다. 결론이 나기 전까지는 단정하지 않겠습니다.",

    # Response (3)
    "response_1": "사고 인지 즉시 관련 시스템을 격리하고, 의심 세션 및 키를 회수했으며, 추가 유출을 막기 위한 차단 조치를 시행했습니다. 동시에 로그 보존과 포렌식 착수를 완료했습니다. 고객 보호를 최우선으로 두고 대응을 진행하고 있습니다.",
    "response_2": "고객 안내는 사실 확인과 1차 차단이 완료된 시점에 맞춰 진행했습니다. 불완전한 정보로 혼란을 키우지 않기 위해, 확인된 범위와 미확정 범위를 분리해 전달했습니다. 추가 확인 내용은 일정 주기로 업데이트하겠습니다.",
    "response_3": "관계 기관 및 외부 보안 전문기관과 협력 중이며, 조사 및 재발 방지 권고안을 즉시 반영하고 있습니다. 법적·규제 준수 요구사항에 맞춰 필요한 신고/보고 절차도 진행하고 있습니다. 진행 상황은 투명하게 공유하겠습니다.",

    # Remedy (3)
    "remedy_1": "피해 가능성이 있는 대상에게는 공지와 함께 전용 지원 채널을 제공하고 있습니다. 상황에 따라 신원보호/모니터링 지원 등 실질적 보호 조치를 포함해 검토하고 있습니다. 구체 기준은 확인 절차와 함께 명확히 안내드리겠습니다.",
    "remedy_2": "개별 피해가 의심되는 경우, 본인 확인 후 우선 조치(계정 보호, 재설정, 추가 인증)와 함께 필요한 지원을 제공하겠습니다. 또한 2차 피해 예방 안내를 단계별로 제공할 예정입니다. 불편을 최소화하는 방향으로 지원하겠습니다.",
    "remedy_3": "전용 문의 채널을 운영하며, 접수된 사례는 우선순위로 처리하고 있습니다. 응답 지연이 발생하지 않도록 인력을 확대 배치했습니다. 문의 경로와 처리 기준은 안내 페이지에 일원화해 제공하겠습니다.",

    # Prevention & Future Plan (3)
    "plan_1": "재발 방지를 위해 접근 권한 관리(최소 권한), 로그/모니터링 고도화, 키/토큰 관리 강화, 정기 침투 테스트를 즉시 강화하겠습니다. 단기·중기·장기 과제로 나눠 일정과 완료 기준을 공개하겠습니다. 실행 결과는 외부 검증도 받겠습니다.",
    "plan_2": "운영 프로세스 전반(권한 부여/회수, 변경관리, 알림 체계)을 재설계하고, 위기 대응 훈련을 정례화하겠습니다. 또한 보안 책임 체계를 명확히 하고 의사결정 기록을 남기겠습니다. ‘다시는 반복되지 않게’ 구조를 바꾸겠습니다.",
    "plan_3": "향후 일정은 (1) 1차 조사 결과 공유, (2) 개선안 공개, (3) 외부 검증 결과 공유의 3단계로 진행하겠습니다. 각 단계별 공개 시점과 범위를 미리 안내하겠습니다. 고객 신뢰 회복을 최우선 목표로 두겠습니다.",
}

# UI에 보여줄 질문 라벨(프론트용)
QUESTIONS = {
    "Cause": [
        ("cause_1", "사고의 원인은 무엇인가요?"),
        ("cause_2", "내부 관리 문제였나요?"),
        ("cause_3", "외부 해킹이었나요?"),
    ],
    "Response": [
        ("response_1", "사고 직후 어떤 조치를 했나요?"),
        ("response_2", "고객에게 언제 알렸나요?"),
        ("response_3", "정부/외부기관과 협력하나요?"),
    ],
    "Remedy": [
        ("remedy_1", "피해 보상은 어떻게 하나요?"),
        ("remedy_2", "이미 피해 입은 사람은요?"),
        ("remedy_3", "지원 창구가 있나요?"),
    ],
    "Prevention & Future Plan": [
        ("plan_1", "재발 방지 대책은?"),
        ("plan_2", "내부 프로세스는 어떻게 바뀌나요?"),
        ("plan_3", "앞으로 계획/일정은요?"),
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

  <div class="overlay" id="overlay">
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

  document.getElementById("closeBtn").onclick = () => {{
    document.getElementById("overlay").style.display = "none";
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
                    "문의 주셔서 감사합니다. 저는 이번 개인정보 유출 사고에 대한 공식 안내를 드리는 AI 대변인입니다.\n"
                    "아래 카테고리에서 질문을 선택하시면, 확인된 사실에 근거해 동일한 형식으로 답변드리겠습니다."
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
