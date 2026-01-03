from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import json
import time

app = FastAPI()


HTML = """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>WebSocket Chat (FastAPI)</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 20px; }
    #log { border: 1px solid #ccc; padding: 12px; height: 60vh; overflow: auto; white-space: pre-wrap; }
    #row { display: flex; gap: 8px; margin-top: 10px; }
    input, button { font-size: 16px; padding: 10px; }
    #name { width: 140px; }
    #msg { flex: 1; }
  </style>
</head>
<body>
  <h2>FastAPI WebSocket 단체 채팅방</h2>
  <div id="log"></div>

  <div id="row">
    <input id="name" placeholder="닉네임" value="guest" />
    <input id="msg" placeholder="메시지 입력 후 Enter" />
    <button id="send">전송</button>
  </div>

  <script>
    const log = document.getElementById("log");
    const nameEl = document.getElementById("name");
    const msgEl = document.getElementById("msg");
    const sendBtn = document.getElementById("send");

    function addLine(s){
      log.textContent += s + "\\n";
      log.scrollTop = log.scrollHeight;
    }

    // 같은 서버에 붙는 ws 주소
    const wsProto = (location.protocol === "https:") ? "wss" : "ws";
    const ws = new WebSocket(`${wsProto}://${location.host}/ws`);

    ws.onopen = () => addLine("[연결됨]");
    ws.onclose = () => addLine("[연결 종료]");
    ws.onerror = () => addLine("[에러 발생]");
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        const ts = new Date(data.ts * 1000).toLocaleTimeString();
        addLine(`[${ts}] ${data.name}: ${data.text}`);
      } catch {
        addLine(ev.data);
      }
    };

    function send(){
      const name = (nameEl.value || "guest").trim();
      const text = (msgEl.value || "").trim();
      if(!text) return;

      ws.send(JSON.stringify({name, text}));
      msgEl.value = "";
      msgEl.focus();
    }

    sendBtn.onclick = send;
    msgEl.addEventListener("keydown", (e) => {
      if(e.key === "Enter") send();
    });
  </script>
</body>
</html>
"""


class ConnectionManager:
    def __init__(self):
        self.active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, message: dict):
        dead = []
        data = json.dumps(message, ensure_ascii=False)
        for ws in list(self.active):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


@app.get("/")
async def home():
    return HTMLResponse(HTML)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        # 입장 알림
        await manager.broadcast({"ts": time.time(), "name": "SYSTEM", "text": "누군가 입장했습니다."})

        while True:
            raw = await ws.receive_text()
            try:
                payload = json.loads(raw)
                name = str(payload.get("name", "guest"))[:20]
                text = str(payload.get("text", ""))[:500]
            except Exception:
                name, text = "guest", raw[:500]

            # (여기서 챗봇 로직을 넣고 싶으면 text를 분석해서 응답을 추가로 broadcast 하면 됨)
            await manager.broadcast({"ts": time.time(), "name": name, "text": text})

    except WebSocketDisconnect:
        manager.disconnect(ws)
        await manager.broadcast({"ts": time.time(), "name": "SYSTEM", "text": "누군가 퇴장했습니다."})
    except Exception:
        manager.disconnect(ws)
if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
