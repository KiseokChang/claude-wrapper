"""세션별 턴 기록 저장소 — sessions/<sid>.jsonl (1줄 = 1턴 기록).

레코드: {"turn_no", "prompt", "cost_usd", "ts", "events": [정규화 이벤트]}
"""
import json
from pathlib import Path


def _session_path(sessions_dir, sid: str) -> Path:
    return Path(sessions_dir) / f"{sid}.jsonl"


def append_turn(sessions_dir, sid: str, record: dict) -> None:
    path = _session_path(sessions_dir, sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_turns(sessions_dir, sid: str) -> list[dict]:
    path = _session_path(sessions_dir, sid)
    if not path.exists():
        return []
    turns = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                turns.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
    return turns


def compact_events(events: list[dict]) -> list[dict]:
    """턴 이벤트 → 재생용 압축.

    - 연속 thinking_delta → thinking 이벤트 1개로 병합 (내용 보존)
    - text_delta는 assistant_text로 대체, init/result는 기록에서 제외
    """
    out = []
    thinking_buf: list[str] = []
    last_sid = None
    for e in events:
        name = e["event"]
        last_sid = e.get("session_id", last_sid)
        if name == "thinking_delta":
            thinking_buf.append(e["data"].get("thinking", ""))
            continue
        if thinking_buf:
            out.append({"event": "thinking", "session_id": last_sid,
                        "data": {"text": "".join(thinking_buf)}})
            thinking_buf = []
        if name in ("text_delta", "init", "result"):
            continue
        out.append(e)
    if thinking_buf:
        out.append({"event": "thinking", "session_id": last_sid,
                    "data": {"text": "".join(thinking_buf)}})
    return out


def list_sessions(sessions_dir) -> list[dict]:
    """세션 요약 목록 — 최근 턴 시각 내림차순.

    요약: sid, turns, total_cost, first_prompt, last_ts
    """
    root = Path(sessions_dir)
    if not root.exists():
        return []
    out = []
    for path in sorted(root.glob("*.jsonl")):
        if path.stem.startswith("turn_"):
            continue  # 서버가 남기는 raw 디버깅 로그 — 세션 아님
        turns = read_turns(root, path.stem)
        if not turns:
            continue
        out.append({"sid": path.stem,
                    "turns": len(turns),
                    "total_cost": sum(t.get("cost_usd") or 0 for t in turns),
                    "first_prompt": turns[0].get("prompt", ""),
                    "last_ts": max(t.get("ts", "") for t in turns)})
    out.sort(key=lambda s: s["last_ts"], reverse=True)
    return out