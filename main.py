from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import json
import time
import os
import csv
import asyncio

# OpenAI (server-side only)
from openai import OpenAI

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# Avatar config (env-based)
AVATAR_MODE = os.environ.get("AVATAR_MODE", "pink")  # pink | photo
AVATAR_URL = os.environ.get("AVATAR_URL", "/static/spokesperson_profile.png")

# =========================
# 0) 실험 설정
# =========================
MAX_QUESTIONS = 3
TIME_LIMIT_SECONDS = 3 * 60  # 3분
FOLLOWUP_CSV_NAME = "followup.csv"

# GPT 모델/프롬프트는 여기서 계속 튜닝하면 됨
MODEL_NAME = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")  # 예시. 배포환경에서 바꿔도 됨.
SYSTEM_PROMPT = """
너는 회사의 공식 입장을 전달하는 AI 대변인이다.
- 확인된 사실만 말한다. 추정/단정/과장 금지.
- 사과(공감) + 현재 확인된 사실 + 회사의 조치 + 앞으로의 안내 순서로 답한다.
- 개인정보/보안 사고 대응에 있어 법적 확정 표현(“~했다” 단정)을 피하고, “현재까지 확인된 바” 형태를 선호한다.
- 불필요하게 길게 쓰지 말고 6~10문장 이내로 답한다.
""".strip()

INCIDENT_FACTS = """
[사건 요약]
- 외부 접근 경로를 통해 일부 고객 개인정보에 대한 무단 접근 발생
- 무단 접근은 2025년 8월 24일경부터 일정 기간 동안 발생한 것으로 파악됨
- 접근 방식 및 정확한 경위는 현재 추가 분석이 진행 중
- 무단 접근이 확인된 정보: 이름, 이메일 주소, 전화번호, 배송지 주소, 일부 주문 정보
- 계정 비밀번호, 로그인 정보, 결제 정보, 신용카드 정보는 포함되지 않음
- 사고 인지 이후 관련 시스템에 대한 접근 제한 조치 및 보안 점검 진행
- 현재 관계 기관과 협력하여 사고 원인 및 영향에 대한 조사 진행 중
- 본 사고로 인한 서비스 중단은 발생하지 않음
""".strip()

client = OpenAI()  # OPENAI_API_KEY 환경변수 사용


# =========================
# 1) UI에 보여줄 추천 질문(프론트용)
# =========================``
QUESTIONS = {
    "Cause": [
        ("q1", "사고 발생 경위가 어떻게 되나요?"),
        ("q2", "발생 시점은 언제인가요?"),
        ("q3", "영향 범위(유출된 정보)는 무엇인가요?"),
    ],
    "Response": [
        ("q4", "사고 이후 회사가 한 조치는 무엇인가요?"),
        ("q5", "현재 서비스는 정상 운영 중인가요?"),
        ("q6", "정부/외부기관과 협력은 어떻게 진행되나요?"),
    ],
    "Remedy": [
        ("q7", "사용자가 지금 당장 해야 할 조치는 뭔가요?"),
        ("q8", "개별 문의/지원은 어디로 하면 되나요?"),
        ("q9", "내 정보 유출 여부는 어떻게 확인하나요?"),
    ],
    "Prevention & Future Plan": [
        ("q10", "재발 방지 계획은 무엇인가요?"),
        ("q11", "추가 업데이트는 어디서 확인하나요?"),
        ("q12", "사고 수습 예상 완료 시점은요?"),
    ],
}

# =========================
# 2) 로그(JSONL) + Followup CSV
# =========================
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "events.jsonl"
FOLLOWUP_CSV = LOG_DIR / FOLLOWUP_CSV_NAME

def log_event(event: dict):
    event.setdefault("ts", time.time())
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

def log_followup(ts: float, sid: str, ip: str | None, text: str):
    is_new = not FOLLOWUP_CSV.exists()
    with FOLLOWUP_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ts", "sid", "ip", "text"])
        if is_new:
            w.writeheader()
        w.writerow({"ts": ts, "sid": sid, "ip": ip, "text": text})


# =========================
# 3) 세션 상태(서버 메모리)
# =========================
SESSIONS: dict[str, dict] = {}
# sid -> {
#   "start_ts": float,
#   "count": int,
#   "phase": "qa" | "followup" | "done",
#   "history": list[dict],  # (선택) GPT 문맥용
# }

def get_session(sid: str):
    s = SESSIONS.get(sid)
    if not s:
        s = {
            "start_ts": time.time(),
            "count": 0,
            "phase": "qa",
            "history": []
        }
        SESSIONS[sid] = s
    return s

def remaining_time(s):
    return max(0, int(TIME_LIMIT_SECONDS - (time.time() - s["start_ts"])))


# =========================
# 4) GPT 호출(서버)
# =========================
def ask_gpt(user_text: str, history: list[dict]) -> str:
    # 너무 길어질 경우를 대비해 history를 적당히 제한(최근 n개만)
    trimmed = history[-10:] if history else []

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": INCIDENT_FACTS},
    ]
    messages.extend(trimmed)
    messages.append({"role": "user", "content": user_text})

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


# =========================
# 5) 단일 페이지 UI
# =========================
HTML = f"""
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>AI Spokesperson Stimulus (GPT)</title>
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
    .page {{
      padding: 28px;
      opacity: .35;
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

    .overlay {{
      position: fixed; inset: 0;
      background: transparent;
      display:flex; align-items:center; justify-content:center;
      padding: 18px;
    }}
    .modal {{
      width: min(980px, 96vw);
      height: min(800px, 88vh);
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
      font-weight: 700;
    }}
    .dot {{
      width: 10px; height: 10px; border-radius: 50%;
      background: #2ecc71;
      box-shadow: 0 0 0 4px rgba(46,204,113,.18);
    }}
    .right-controls {{
      display:flex; align-items:center; gap:10px;
    }}
    .timer {{
      font-weight: 800;
      color: #111827;
      border: 1px solid var(--line);
      background: #fafafa;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 12px;
    }}
    .exit {{
      border:none; background:transparent; font-size: 14px; cursor:pointer;
      color: var(--muted);
      padding: 8px 10px;
      border-radius: 10px;
      border: 1px solid var(--line);
    }}
    .exit:hover {{
      color: #111827;
      background: #fafafa;
    }}

    .modal-body {{
      flex: 1;
      display: flex;
      flex-direction: column;
      background: linear-gradient(180deg, #fff 0%, #fafbff 100%);
      min-height: 0;
    }}

    .agent {{
      display:flex; flex-direction:column; align-items:center;
      padding: 18px 18px 0 18px;
      gap: 8px;
      margin-bottom: 14px;
      flex: 0 0 auto;
    }}
    .avatar {{
      width: 116px; height: 116px; border-radius: 50%;
      display:grid; place-items:center;
      background: radial-gradient(circle at 30% 30%, #ffe6f2, #fff);
      border: 2px solid #f3f4f7;
      box-shadow: 0 12px 25px rgba(0,0,0,.12);
      overflow:hidden;
    }}
    .avatar img {{
      width: 104px; height: 104px; object-fit: cover;
    }}
    .agent-name {{
      font-weight: 800;
      color: var(--accent);
    }}

    .chat {{
      flex: 1;
      min-height: 0;
      padding: 12px 18px 10px 18px;
      overflow: auto;
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
    .bubble.user {{
      background: #fff0f6;
      border-color: #ffd0e2;
    }}

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
    }}
    .input {{
      flex:1;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px 12px;
      background: #fff;
      font-size: 14px;
      outline: none;
    }}
    .send {{
      border:none;
      background: var(--accent);
      color:#fff;
      padding: 11px 14px;
      border-radius: 12px;
      font-weight: 800;
      cursor:pointer;
    }}
    .send:disabled {{
      opacity: .45;
      cursor:not-allowed;
    }}
    .hint {{
      font-size: 12px;
      color: var(--muted);
      padding: 0 18px 12px 18px;
      background:#fff;
    }}

    .priming-wrap {{
      position: fixed;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 40px 22px;
      background: var(--bg);
      z-index: 5;
    }}
    .priming-card {{
      width: min(980px, 96vw);
      background: #fff;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow:hidden;
      max-height: 92vh;
      min-height: 0;
      display: flex;
      flex-direction: column;
    }}
    .priming-top {{
      position: sticky;
      top: 0;
      z-index: 2;
      padding: 18px;
      background: #fff;
      flex: 0 0 auto;
    }}
    .mid-driver{{
      height: 1px;
      background: var(--line);
      margin: 14px 0 12px 0;
    }}
    .priming-mid{{
      flex: 1 1 auto;
      min-height: 0;
      overflow: auto;
    }}
    .news-img{{
      border-radius: 14px;
      border: 1px solid var(--line);
      background: linear-gradient(180deg, #ffffff 0%, #fafafa 100%);
      padding: 18px;
    }}
    .news-photo {{
      display: block;
      width: 100%;
      height: auto;
      object-fit: cover;
      margin-top: -16px;
      border-radius: 12px;
      border: 1px solid var(--line);
    }}
    .news-headline{{
      font-weight: 900;
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
      flex: 1 1 auto;
      min-height: 0;
      overflow: auto;
    }}
    .priming-title{{
      font-weight: 900;
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
      align-items: center;
    }}
    .priming-cta{{
      border: none;
      background: var(--accent);
      color: #fff;
      font-weight: 900;
      padding: 12px 14px;
      border-radius: 12px;
      cursor: pointer;
    }}
    .priming-note{{
      font-size: 12px;
      color: var(--muted);
    }}
    /* typing indicator bubble */
    .typing {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      }}
    .typing .dots {{
      display: inline-flex;
      gap: 4px;
    }}
    .typing .dots span {{
      width: 6px;
      height: 6px;
      border-radius: 999px;
      background: var(--muted);
      opacity: .25;
      animation: blink 1.1s infinite;
    }}
    .typing .dots span:nth-child(2) {{ animation-delay: .15s; }}
    .typing .dots span:nth-child(3) {{ animation-delay: .30s; }}
    @keyframes blink {{
      0%, 80%, 100% {{ opacity: .25; transform: translateY(0); }}
      40% {{opacity: 1; transform: translateY(-2px); }}
    }}
  </style>
</head>
<body>
<div id="endOverlay" style="
  display:none;
  position:fixed; inset:0;
  background: rgba(0,0,0,.45);
  z-index: 9999;
  align-items:center; justify-content:center;
  padding: 18px;
">
  <div style="
    width: min(520px, 92vw);
    background: #fff;
    border: 1px solid var(--line);
    border-radius: 16px;
    box-shadow: var(--shadow);
    padding: 18px;
  ">
    <div style="font-weight:900; font-size:16px; margin-bottom:10px;">
      대화가 종료되었습니다
    </div>
    <div style="color: var(--muted); line-height:1.5; font-size:14px; margin-bottom:14px;">
      아래 버튼을 눌러 이 창을 닫고, 나머지 설문에 응답해 주시기 바랍니다.
    </div>
    <div style="display:flex; gap:10px; justify-content:flex-end;">
      <button id="closeWindowBtn" style="
        border:none;
        background: var(--accent);
        color:#fff;
        font-weight:900;
        padding: 10px 12px;
        border-radius: 12px;
        cursor:pointer;
      ">창 닫기</button>
    </div>
    <div id="closeFailHint" style="display:none; margin-top:10px; font-size:12px; color: var(--muted);">
      ※ 브라우저 설정에 따라 자동으로 창이 닫히지 않을 수 있습니다. 이 경우 탭(창)을 직접 닫아주세요.
    </div>
  </div>
</div>
  <div class="priming-wrap" id="priming">
    <div class="priming-card">
      <div class="priming-top">
        <div class="news-img">
          <div class="news-headline">[속보] AI 보안 시스템 운영 대형 커머스 기업, 개인정보 유출</div>
          <div class="news-sub">외부 접근으로 고객 정보 노출… 기업 “경위 조사 중”</div>
        </div>
      </div>

      <div class="priming-mid">
        <img src="/static/fake_news_v1.png" alt="개인정보 유출 관련 뉴스 이미지" class="news-photo" />
        <div class="mid-driver"></div>
        <div class="priming-title">📌 사건 요약</div>
        <ul class="priming-bullets">
          <li>당신은 방금 개인정보 유출 관련 안내를 받았습니다.</li>
          <li>유출 여부 확인 결과, 당신의 계정 정보가 이번 사고 영향 범위에 포함된 것으로 표시되었습니다.</li>
          <li><b>유출된 정보:</b> 이름, 이메일 주소, 전화번호, 배송지 주소, 일부 주문 정보</li>
          <li><b>유출되지 않은 정보:</b> 계정 비밀번호, 결제 정보, 신용카드 정보</li>
          <li><b>진행 방식:</b> 추천 질문을 참고해 직접 타이핑 후 전송합니다 (최대 3회)</li>
        </ul>
      </div>

      <div class="priming-bottom">
        <button class="priming-cta" id="startChatBtn">AI 대변인의 공식 대응 확인하기</button>
        <div class="priming-note">※ 총 대화 시간 3분 / 질문 3회 제한</div>
      </div>
    </div>
  </div>

  <div class="overlay" id="overlay" style="display:none">
    <div class="modal">
      <div class="modal-header">
        <div class="status"><span class="dot"></span><span>Online</span></div>
        <div class="right-controls">
          <div class="timer" id="timer">03:00</div>
          <button class="exit" id="exitBtn" aria-label="exit">Exit</button>
        </div>
      </div>

      <div class="modal-body">
        <div class="agent">
          <div class="avatar" title="AI Spokesperson">
            {f'<img src="{AVATAR_URL}" alt="AI Spokesperson" />' if AVATAR_MODE == "photo" else ''}
          </div>
          <div class="agent-name" id="agentName">Eline</div>
        </div>

        <div class="chat" id="chat"></div>

        <div class="bottom-area">
          <div class="chips" id="chips"></div>

          <div class="composer">
            <input class="input" id="input" placeholder="추천 질문을 클릭해 텍스트를 입력하거나, 직접 질문을 키보드로 입력하세요 (최대 3회)" />
            <button class="send" id="sendBtn">Send</button>
          </div>

          <div class="hint" id="hint">※ 추천 질문은 참고용입니다. 클릭하면 입력창에 자동 입력됩니다.</div>
        </div>
      </div>
    </div>
  </div>

<script>
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
  const input = document.getElementById("input");
  const sendBtn = document.getElementById("sendBtn");
  const hint = document.getElementById("hint");
  const timerEl = document.getElementById("timer");
  const exitBtn = document.getElementById("exitBtn");
  const endOverlay = document.getElementById("endOverlay");
  const closeWindowBtn = document.getElementById("closeWindowBtn");
  const closeFailHint = document.getElementById("closeFailHint");

  let endOverlayScheduled = false;

  function showEndOverlay() {{
    endOverlay.style.display = "flex";
  }}

  closeWindowBtn.onclick = () => {{
    // 시도
    window.close();

    // 실패 대비: 400ms 후에도 창이 안 닫혔다고 가정되면 안내문 표시
    setTimeout(() => {{
      closeFailHint.style.display = "block";
    }}, 400);
  }};

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

  let typingRowEl = null;

function showTyping() {{
  if (typingRowEl) return;
  const row = document.createElement("div");
  row.className = "bubble-row ai";
  const bubble = document.createElement("div");
  bubble.className = "bubble ai";

  const wrap = document.createElement("div");
  wrap.className = "typing";
  wrap.innerHTML = `
    <span class="dots"><span></span><span></span><span></span></span>
  `;
  bubble.appendChild(wrap);
  row.appendChild(bubble);
  chat.appendChild(row);
  chat.scrollTop = chat.scrollHeight;

  typingRowEl = row;
}}

function hideTyping() {{
  if (!typingRowEl) return;
  typingRowEl.remove();
  typingRowEl = null;
}}
  
  // recommended chips: click -> fill input (not send)
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
        input.value = label;
        input.focus();
      }};
      chips.appendChild(q);
    }});
  }}

  renderCategories();

  // websocket
  const wsProto = (location.protocol === "https:") ? "wss" : "ws";
  const ws = new WebSocket(`${{wsProto}}://${{location.host}}/ws?sid=${{encodeURIComponent(sid)}}`);

  function wsSend(obj) {{
    if(ws.readyState === 1) ws.send(JSON.stringify(obj));
  }}

  let state = {{
    phase: "qa",          // qa | followup | done
    remainingQuestions: 3,
    remainingSeconds: 180
  }};

  function setUIEnabled(enabled) {{
    input.disabled = !enabled;
    sendBtn.disabled = !enabled;
  }}

  function updateHint() {{
    if(state.phase === "qa") {{
      hint.textContent = `※ 남은 질문 횟수: ${{state.remainingQuestions}} / 3 (총 3분 제한)`;
    }} else if(state.phase === "followup") {{
      hint.textContent = "※ 마지막으로 추천 질문 외 추가로 묻고 싶은 질문을 입력해 주세요 (이 답변은 별도 저장됩니다).";
      input.placeholder = "궁금한 추가 질문을 입력해주세요 (1회)";
    }} else {{
      hint.textContent = "※ 대화가 종료되었습니다. Exit 또는 새로고침으로 종료할 수 있습니다.";
    }}
  }}

  function formatTime(sec) {{
    const m = String(Math.floor(sec / 60)).padStart(2, "0");
    const s = String(sec % 60).padStart(2, "0");
    return `${{m}}:${{s}}`;
  }}

  function tickTimer() {{
    timerEl.textContent = formatTime(state.remainingSeconds);
    if(state.remainingSeconds <= 0) {{
      setUIEnabled(false);
      state.phase = "done";
      updateHint();
      addBubble("AI", "대화 시간이 종료되었습니다. 참여해주셔서 감사합니다.");
      try {{ ws.close(); }} catch(e) {{}}
      return;
    }}
    state.remainingSeconds -= 1;
    setTimeout(tickTimer, 1000);
  }}

  ws.onopen = () => {{
    wsSend({{ type: "hello", sid }});
  }};

  ws.onmessage = (ev) => {{
    try {{
      const msg = JSON.parse(ev.data);
      if(msg.type === "ai") {{
        // ✅ (D-1) 생성중 표시 제거
        hideTyping();
        // 기존대로 AI 말풍선 추가
        addBubble("AI", msg.text);
        // ✅ (D-2) 입력 다시 활성화 (세션 done이면 제외)
        if(state.phase !== "done") setUIEnabled(true);
      }}
      if(msg.type === "state") {{
        state.phase = msg.phase;
        state.remainingQuestions = msg.remainingQuestions;
        state.remainingSeconds = msg.remainingSeconds;
        updateHint();
        timerEl.textContent = formatTime(state.remainingSeconds);
        if(state.phase === "done") {{
          setUIEnabled(false);
          
          // 3~5초 후 종료 안내 오버레이
          if(!endOverlayScheduled) {{
            endOverlayScheduled = true;
            setTimeout(showEndOverlay, 4000); // 4초
          }}
        }}
      }}
    }} catch(e) {{}}
  }};

  ws.onerror = () => {{
    hideTyping();
    setUIEnabled(true);
    addBubble("AI", "[연결 오류] 네트워크 상태를 확인해 주세요.");
  }};

  ws.onclose = () => {{
    hideTyping();
    // no spam
  }};

  function sendText() {{
    const text = (input.value || "").trim();
    if(!text) return;

    if(state.phase === "qa") {{
      addBubble("USER", text);
      setUIEnabled(false);
      showTyping();
      wsSend({{ type: "user_message", sid, text }});
      input.value = "";
    }} else if(state.phase === "followup") {{
      addBubble("USER", text);
      wsSend({{ type: "followup_answer", sid, text }});
      input.value = "";
      setUIEnabled(false);
    }}
  }}

  sendBtn.onclick = sendText;
  input.addEventListener("keydown", (e) => {{
    if(e.key === "Enter") {{
      e.preventDefault();
      sendText();
    }}
  }});

  // Exit: close ws + hide overlay + show end message
  exitBtn.onclick = () => {{
    try {{ ws.close(); }} catch(e) {{}}
    document.getElementById("overlay").style.display = "none";
    document.getElementById("priming").style.display = "flex";
  }};

  // priming -> chat
  const priming = document.getElementById("priming");
  const overlay = document.getElementById("overlay");
  document.getElementById("startChatBtn").onclick = () => {{
    priming.style.display = "none";
    overlay.style.display = "flex";
    updateHint();
    tickTimer();
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
    await ws.accept()

    sid = None
    try:
        sid = ws.query_params.get("sid")
    except Exception:
        sid = None
    sid = (sid or "unknown")[:64]

    client_ip = ws.client.host if ws.client else None

    s = get_session(sid)
    log_event({"event": "connect", "sid": sid, "ip": client_ip})

    async def send_state():
        await ws.send_text(json.dumps({
            "type": "state",
            "phase": s["phase"],
            "remainingQuestions": max(0, MAX_QUESTIONS - s["count"]),
            "remainingSeconds": remaining_time(s),
        }, ensure_ascii=False))

    try:
        while True:
            raw = await ws.receive_text()
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"type": "unknown", "raw": raw}

            mtype = payload.get("type")

            # 시간 제한 체크 (서버 기준)
            if remaining_time(s) <= 0 and s["phase"] != "done":
                s["phase"] = "done"
                log_event({"event": "time_over", "sid": sid})
                await send_state()
                await ws.send_text(json.dumps({
                    "type": "ai",
                    "text": "대화 시간이 종료되었습니다. 참여해주셔서 감사합니다."
                }, ensure_ascii=False))
                await ws.close()
                break

            if mtype == "hello":
                log_event({"event": "hello", "sid": sid})
                first_msg = (
                    "안녕하세요. 저는 본 사건에 대해 회사의 공식 입장을 전달하는 AI 대변인 Eline입니다.\n\n"
                    "먼저 이번 개인정보 유출 사고로 불편과 걱정을 드린 점 사과드립니다.\n\n"
                    "추천 질문을 참고해 궁금하신 내용을 직접 입력해 주세요. (최대 3회 / 총 3분)"
                )
                await ws.send_text(json.dumps({"type": "ai", "text": first_msg}, ensure_ascii=False))
                await send_state()

            elif mtype == "user_message":
                if s["phase"] != "qa":
                    log_event({"event": "blocked_message_phase", "sid": sid, "phase": s["phase"]})
                    await ws.send_text(json.dumps({
                        "type": "ai",
                        "text": "현재 단계에서는 이 입력을 받을 수 없습니다."
                    }, ensure_ascii=False))
                    await send_state()
                    continue

                if s["count"] >= MAX_QUESTIONS:
                    s["phase"] = "followup"
                    log_event({"event": "blocked_message_limit", "sid": sid})
                    await send_state()
                    await ws.send_text(json.dumps({
                        "type": "ai",
                        "text": "질문 횟수(3회)가 모두 사용되었습니다. 마지막으로 추가로 하고 싶은 말씀이 있나요?"
                    }, ensure_ascii=False))
                    continue

                user_text = str(payload.get("text", ""))[:2000].strip()
                if not user_text:
                    await send_state()
                    continue

                # 로그
                log_event({"event": "user_message", "sid": sid, "text": user_text[:500]})
                # 🔔 typing ON (GPT 응답 생성 시작)
                await ws.send_text(json.dumps({
                    "type": "typing",
                    "on": True
                }, ensure_ascii=False))

                # GPT 호출 (blocking 방지: thread로 돌림)
                try:
                    s["history"].append({"role": "user", "content": user_text})
                    answer = await asyncio.to_thread(ask_gpt, user_text, s["history"])
                    s["history"].append({"role": "assistant", "content": answer})
                except Exception as e:
                    log_event({"event": "gpt_error", "sid": sid, "err": str(e)[:300]})
                    try:
                         await ws.send_text(json.dumps({
                              "type": "typing",
                              "on": False
                         }, ensure_ascii=False))
                    except Exception:
                        pass

                    answer = "현재 응답 생성 과정에서 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."

                # 🔕 typing OFF (GPT 응답 생성 종료)
                await ws.send_text(json.dumps({
                    "type": "typing",
                    "on": False
                }, ensure_ascii=False))

                await ws.send_text(json.dumps({"type": "ai", "text": answer}, ensure_ascii=False))

                # 카운트 증가
                s["count"] += 1
                log_event({"event": "count_inc", "sid": sid, "count": s["count"]})
                await send_state()

                # 3회 도달하면 followup 안내
                if s["count"] >= MAX_QUESTIONS and s["phase"] == "qa":
                    s["phase"] = "followup"
                    log_event({"event": "enter_followup", "sid": sid})
                    await send_state()
                    await ws.send_text(json.dumps({
                        "type": "ai",
                        "text": "마지막으로 추가로 하고 싶은 말씀이 있나요? (이 답변은 별도로 저장됩니다.)"
                    }, ensure_ascii=False))

            elif mtype == "followup_answer":
                if s["phase"] != "followup":
                    log_event({"event": "blocked_followup_phase", "sid": sid, "phase": s["phase"]})
                    await send_state()
                    continue

                text = str(payload.get("text", ""))[:4000].strip()
                if not text:
                    await send_state()
                    continue

                ts = time.time()
                log_event({"event": "followup_answer", "sid": sid, "text": text[:500]})
                log_followup(ts=ts, sid=sid, ip=client_ip, text=text)

                s["phase"] = "done"
                log_event({"event": "done", "sid": sid})
                await send_state()

                await ws.send_text(json.dumps({
                    "type": "ai",
                    "text": "감사합니다. AI 대변인과의 대화가 종료되었습니다."
                }, ensure_ascii=False))
                await ws.close()
                break

            elif mtype == "exit":
                log_event({"event": "exit", "sid": sid})
                s["phase"] = "done"
                await send_state()
                await ws.close()
                break

            else:
                log_event({"event": "unknown_input", "sid": sid, "raw": str(payload)[:500]})
                await ws.send_text(json.dumps({
                    "type": "ai",
                    "text": "알 수 없는 요청입니다."
                }, ensure_ascii=False))
                await send_state()

    except WebSocketDisconnect:
        log_event({"event": "disconnect", "sid": sid})
    except Exception as e:
        log_event({"event": "error", "sid": sid, "err": str(e)[:300]})
        try:
            await ws.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
