"""claude -p 워크벤치 서버 — FastAPI + WebSocket.

1 턴 = claude -p(또는 ollama launch claude -- ... -p) 서브프로세스 1회.
터치 종료 시 result.session_id 를 저장하고 다음 턴 --resume 으로 이어감.
엔진 선택(DIRECT/OLLAMA)은 config.json 에 영속화.
"""
import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path

import psutil
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse, JSONResponse

import parser as ps
import session_store as ss
from config_store import DEFAULTS, load_config, save_config
from file_browser import list_dir, read_file

BASE = Path(__file__).parent
CONFIG_PATH = BASE / "config.json"
SESSIONS_DIR = BASE / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)


def workspace_dir() -> Path:
    ws = BASE / load_config(CONFIG_PATH).get("workspace", DEFAULTS["workspace"])
    ws.mkdir(exist_ok=True)
    return ws

app = FastAPI()


def _resolve(exe: str) -> str:
    """Windows: claude 는 확장자 없는 npm shell script → claude.CMD 로 해석."""
    return shutil.which(exe) or exe


def build_cmd(text: str, cfg: dict, resume_sid: str | None, skip_permissions: bool) -> list[str]:
    tail = ["--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose"]
    if skip_permissions:
        tail.append("--dangerously-skip-permissions")
    else:
        tail += ["--permission-mode", "default"]
    if cfg.get("max_budget_usd"):  # 0/None = 미설정
        tail += ["--max-budget-usd", str(cfg["max_budget_usd"])]
    if resume_sid:
        tail += ["--resume", resume_sid]
    if cfg["engine"] == "OLLAMA":
        return ([_resolve("ollama"), "launch", "claude", "--model", cfg["ollama_model"], "--",
                 "-p", text] + tail)
    return [_resolve("claude"), "-p", text] + tail


class TurnRunner:
    """한 턴 = 서브프로세스 1회 실행 + 이벤트 브로드캐스트."""

    def __init__(self):
        self.session_id: str | None = None
        self.turn_no = 0
        self.busy = False

    async def run_turn(self, ws: WebSocket, text: str, cfg: dict,
                       skip_permissions: bool) -> None:
        self.turn_no += 1
        self.busy = True
        log_path = SESSIONS_DIR / f"turn_{self.turn_no:04d}.jsonl"
        log = log_path.open("a", encoding="utf-8")
        try:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *build_cmd(text, cfg, self.session_id, skip_permissions),
                    cwd=BASE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except OSError as e:  # 실행 파일 부재 등 스폰 실패
                await ws.send_json({"event": "proc_error", "data": str(e)})
                return
            assert proc.stdout is not None
            final_result = None
            all_events = []  # 재생용 기록 — 델타 포함 수집 후 compact_events로 압축
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                log.write(line + "\n")
                log.flush()
                ev = ps.parse_line(line)
                if ev is None:
                    continue
                if ev["event"] == "result":
                    final_result = ev
                all_events.append(ev)
                await ws.send_json(ev)
            await proc.wait()
            if proc.returncode != 0:
                err = await proc.stderr.read() if proc.stderr else b""
                await ws.send_json({"event": "proc_error",
                                    "data": err.decode("utf-8", errors="replace")[-2000:]})
            if final_result:
                self.session_id = final_result["session_id"]
                ss.append_turn(SESSIONS_DIR, self.session_id, {
                    "turn_no": self.turn_no,
                    "prompt": text,
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "cost_usd": final_result["data"].get("total_cost_usd"),
                    "events": ss.compact_events(all_events),
                })
                summary = {"subtype": final_result["data"].get("subtype"),
                           "is_error": final_result["data"].get("is_error"),
                           "cost_usd": final_result["data"].get("total_cost_usd"),
                           "duration_ms": final_result["data"].get("duration_ms"),
                           "session_id": self.session_id}
                await ws.send_json({"event": "turn_done", "data": summary})
        finally:
            log.close()
            self.busy = False


runner = TurnRunner()


@app.get("/")
async def index():
    return FileResponse(BASE / "index.html")


@app.get("/api/config")
async def get_config():
    return JSONResponse(load_config(CONFIG_PATH))


@app.get("/api/sessions")
async def get_sessions():
    return JSONResponse(ss.list_sessions(SESSIONS_DIR))


@app.get("/api/sessions/{sid}")
async def get_session_turns(sid: str):
    return JSONResponse(ss.read_turns(SESSIONS_DIR, sid))


@app.get("/api/files")
async def get_files(dir: str = ""):
    entries = list_dir(workspace_dir(), dir)
    if entries is None:
        return JSONResponse({"error": "invalid path"}, status_code=400)
    return JSONResponse(entries)


@app.get("/api/file")
async def get_file(path: str = ""):
    data = read_file(workspace_dir(), path)
    if data is None:
        return JSONResponse({"error": "invalid path"}, status_code=400)
    return JSONResponse(data)


@app.get("/api/stats")
async def get_stats():
    """경량 리소스 모니터 — 가이드 §9.3 Governor의 workbench 시작점."""
    sessions = ss.list_sessions(SESSIONS_DIR)
    return JSONResponse({
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "ram_percent": psutil.virtual_memory().percent,
        "ram_used_gb": round(psutil.virtual_memory().used / 2**30, 1),
        "sessions": len(sessions),
        "turns": runner.turn_no,
        "busy": runner.busy,
        "engine": cfg_engine(),
    })


def cfg_engine() -> str:
    return load_config(CONFIG_PATH)["engine"]


@app.post("/api/config")
async def set_config(cfg: dict):
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in cfg.items() if k in DEFAULTS})
    save_config(CONFIG_PATH, merged)
    return JSONResponse(merged)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    cfg = load_config(CONFIG_PATH)
    await ws.send_json({"event": "config", "data": cfg})
    skip_permissions = False
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            action = msg.get("action")

            if action == "set_engine":
                cfg["engine"] = msg["engine"]
                if msg.get("ollama_model"):
                    cfg["ollama_model"] = msg["ollama_model"]
                save_config(CONFIG_PATH, cfg)          # 영속화 — 재기동해도 유지
                await ws.send_json({"event": "config", "data": cfg})

            elif action == "set_mode":
                skip_permissions = bool(msg.get("skip_permissions", False))
                await ws.send_json({"event": "mode",
                                    "data": {"skip_permissions": skip_permissions}})

            elif action == "set_budget":
                # 턴 비용 한도 — config.json에 영속화, 다음 턴부터 적용
                raw = msg.get("max_budget_usd")
                cfg["max_budget_usd"] = float(raw) if raw not in (None, "", 0) else None
                save_config(CONFIG_PATH, cfg)
                await ws.send_json({"event": "config", "data": cfg})

            elif action == "reset":
                runner.session_id = None
                runner.turn_no = 0
                await ws.send_json({"event": "reset"})

            elif action == "load_session":
                # 이력 선택 — 같은 세션으로 이어가기(resume) 위해 runner에 sid 세팅
                if runner.busy:
                    await ws.send_json({"event": "busy"})
                    continue
                sid = msg.get("sid")
                turns = ss.read_turns(SESSIONS_DIR, sid)
                runner.session_id = sid if turns else None
                await ws.send_json({"event": "session_loaded",
                                    "data": {"sid": sid, "turns": turns}})

            elif action == "send":
                if runner.busy:
                    await ws.send_json({"event": "busy"})
                    continue
                # per-turn 스킵 우선(재시도 버튼), 없으면 연결 레벨 설정
                use_skip = bool(msg.get("skip_permissions", skip_permissions))
                await runner.run_turn(ws, msg["text"], cfg, use_skip)

    except Exception:
        return  # 연결 종료