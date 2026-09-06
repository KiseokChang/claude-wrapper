"""텔레그램 브릿지 — claude -p(또는 ollama launch)를 엔진으로 쓰는 개인 ChatOps 봇.

workbench의 parser/config_store/build_cmd 를 재사용. 롱 폴링 방식.
토큰은 workbench/.telegram_token 파일로 관리 (git 제외).
실행: PYTHONIOENCODING=utf-8 python telegram_bridge.py
"""
import asyncio
import json
import sys
from pathlib import Path

import aiohttp

import parser as ps
from config_store import load_config
from server import BASE, build_cmd

CONFIG_PATH = BASE / "config.json"
TOKEN_PATH = BASE / ".telegram_token"
TG_API = "https://api.telegram.org/bot{token}/{method}"
TG_LIMIT = 4096


# ---------- 순수 로직 ----------

def load_token(path) -> str:
    try:
        token = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        raise RuntimeError(
            f"토큰 파일이 없습니다: {path}\n"
            "BotFather에서 발급받은 토큰을 한 줄로 저장해 주세요.")
    if not token:
        raise RuntimeError(f"토큰 파일이 비어 있습니다: {path}")
    return token


def make_keyboard(choices: list[str]) -> dict | None:
    """선택지 → Telegram InlineKeyboardMarkup (콜백: choice:<index>)."""
    if not choices:
        return None
    return {"inline_keyboard": [
        [{"text": c, "callback_data": f"choice:{i}"}] for i, c in enumerate(choices)
    ]}


def split_for_telegram(text: str, limit: int = TG_LIMIT) -> list[str]:
    """텔레그램 4096자 제한 대응 — 내용 손실 없이 분할."""
    if len(text) <= limit:
        return [text]
    return [text[i:i + limit] for i in range(0, len(text), limit)]


def parse_skip_command(text: str) -> bool | None:
    """/skip on|off 커맨드 파싱 — on→True, off→False, 그 외→None."""
    parts = (text or "").strip().lower().split()
    if len(parts) != 2 or parts[0] != "/skip":
        return None
    if parts[1] == "on":
        return True
    if parts[1] == "off":
        return False
    return None


def build_reply(events: list[dict]) -> tuple[str, list[str]]:
    """한 턴의 정규화 이벤트들 → (응답 텍스트, 선택지)."""
    texts = []
    denials = []
    final_result = None
    for ev in events:
        d = ev.get("data") or {}
        if ev["event"] == "assistant_text":
            texts.append(d.get("text", ""))
        elif ev["event"] == "tool_result" and d.get("is_error"):
            denials.append(str(d.get("content", ""))[:300])
        elif ev["event"] == "result":
            final_result = d
    reply = ""
    if denials:
        reply += "⚠️ 권한 거부:\n" + "\n".join("· " + s for s in denials) + "\n\n"
        reply += "(/skip on 입력 시 이후 턴은 권한 확인 없이 실행)\n\n"
    reply += "\n".join(texts) or "(응답 없음)"
    if final_result and final_result.get("total_cost_usd"):
        reply += f"\n\n— ${final_result['total_cost_usd']:.3f}"
    choices = ps.extract_choices(reply)  # 비용 라인 포함해도 번호 패턴은 정상 추출
    return reply, choices


# ---------- 봇 본체 ----------

class TelegramBridge:
    def __init__(self, token: str):
        self.token = token
        self.sessions: dict[int, str | None] = {}   # chat_id -> session_id
        self.choices: dict[int, list[str]] = {}     # chat_id -> 마지막 선택지
        self.skip_perms: dict[int, bool] = {}       # chat_id -> 권한 스킵 여부
        self.busy_chats: set[int] = set()
        self.api = TG_API.format(token=token, method="{method}")

    async def call(self, http: aiohttp.ClientSession, method: str, payload: dict):
        async with http.post(self.api.format(method=method), json=payload) as resp:
            data = await resp.json()
            if not data.get("ok"):
                print(f"[TG 오류] {method}: {data}", file=sys.stderr)
            return data

    async def send_text(self, http, chat_id: int, text: str, keyboard: dict | None = None):
        for i, piece in enumerate(split_for_telegram(text)):
            payload = {"chat_id": chat_id, "text": piece}
            if keyboard and i == len(split_for_telegram(text)) - 1:
                payload["reply_markup"] = keyboard
            await self.call(http, "sendMessage", payload)

    async def run_turn(self, http, chat_id: int, text: str):
        cfg = load_config(CONFIG_PATH)
        events = []
        sid = self.sessions.get(chat_id)
        cmd = build_cmd(text, cfg, sid, skip_permissions=self.skip_perms.get(chat_id, False))
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=BASE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        assert proc.stdout
        final = None
        async for raw in proc.stdout:
            ev = ps.parse_line(raw.decode("utf-8", errors="replace").rstrip("\n"))
            if ev is None:
                continue
            events.append(ev)
            if ev["event"] == "tool_use":
                await self.call(http, "sendChatAction",
                                {"chat_id": chat_id, "action": "typing"})
            if ev["event"] == "result":
                final = ev
        await proc.wait()
        if proc.returncode != 0:
            err = await proc.stderr.read() if proc.stderr else b""
            await self.send_text(http, chat_id, "❌ 프로세스 오류:\n" + err.decode("utf-8", errors="replace")[-1500:])
            return
        if final:
            self.sessions[chat_id] = final["session_id"]
        reply, choices = build_reply(events)
        self.choices[chat_id] = choices
        await self.send_text(http, chat_id, reply, make_keyboard(choices))

    async def handle_update(self, http, update: dict):
        cb = update.get("callback_query")
        if cb:
            chat_id = cb["message"]["chat"]["id"]
            data = cb.get("data", "")
            if data.startswith("choice:"):
                idx = int(data.split(":")[1])
                options = self.choices.get(chat_id) or []
                if idx < len(options):
                    await self.call(http, "answerCallbackQuery", {"callback_query_id": cb["id"]})
                    await self.send_text(http, chat_id, "▶ 선택: " + options[idx])
                    await self.run_turn(http, chat_id, options[idx])
            return
        msg = update.get("message")
        if not msg or "text" not in msg:
            return
        chat_id = msg["chat"]["id"]
        text = msg["text"]
        if chat_id in self.busy_chats:
            await self.send_text(http, chat_id, "(이전 턴 실행 중 — 잠시 후 다시 시도)")
            return
        if text.strip() == "/reset":
            self.sessions[chat_id] = None
            self.choices[chat_id] = []
            await self.send_text(http, chat_id, "🔄 세션 리셋됨 — 새 대화 시작")
            return
        skip = parse_skip_command(text)  # 권한 스킵 토글 — busy 가드보다 먼저 처리
        if skip is not None:
            self.skip_perms[chat_id] = skip
            state = "이후 턴부터 권한 확인 없이 실행됩니다" if skip else "권한 확인 모드로 복귀합니다"
            await self.send_text(http, chat_id, "🔓 권한 스킵 " + ("ON" if skip else "OFF") + " — " + state)
            return
        self.busy_chats.add(chat_id)
        try:
            await self.run_turn(http, chat_id, text)
        finally:
            self.busy_chats.discard(chat_id)

    async def loop(self):
        offset = 0
        async with aiohttp.ClientSession() as http:
            me = await self.call(http, "getMe", {})
            print(f"[브릿지 시작] @{me['result']['username']} — 엔진: {load_config(CONFIG_PATH)['engine']}")
            while True:
                resp = await self.call(http, "getUpdates",
                                       {"offset": offset, "timeout": 30})
                for update in resp.get("result", []):
                    offset = update["update_id"] + 1
                    try:
                        await self.handle_update(http, update)
                    except Exception as e:
                        print(f"[업데이트 처리 오류] {e}", file=sys.stderr)


if __name__ == "__main__":
    token = load_token(TOKEN_PATH)
    asyncio.run(TelegramBridge(token).loop())