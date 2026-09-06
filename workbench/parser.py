"""claude -p stream-json NDJSON 라인 파서 — 실측 스키마 기준(CLI 2.1.109)."""
import json

# 무시할 event.type (델타 스트림 내부)
_IGNORED_STREAM_EVENTS = {
    "message_start", "message_delta", "message_stop",
    "content_block_stop",
}
# 무시할 최상위 type
_IGNORED_TYPES = {
    "system",        # init 제외 — hook_started/hook_response/status
    "stream_event",  # 아래에서 관심 있는 것만 통과
}


def parse_line(line: str) -> dict | None:
    """NDJSON 한 줄을 정규화 이벤트로 변환. 관심 없으면 None.

    정규화 이벤트: init, text_delta, thinking_delta, tool_use,
    assistant_text, tool_result, result, raw
    공통 키: event, session_id, data
    """
    stripped = line.strip()
    if not stripped:
        return None
    try:
        d = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return {"event": "raw", "data": line}
    if not isinstance(d, dict):
        return {"event": "raw", "data": line}

    t = d.get("type")
    sid = d.get("session_id")

    if t == "system":
        if d.get("subtype") == "init":
            return {"event": "init", "session_id": sid, "data": d}
        return None

    if t == "stream_event":
        ev = d.get("event") or {}
        et = ev.get("type")
        if et == "content_block_delta":
            delta = ev.get("delta") or {}
            dt = delta.get("type")
            if dt == "text_delta":
                return {"event": "text_delta", "session_id": sid,
                        "data": {"text": delta.get("text", "")}}
            if dt == "thinking_delta":
                return {"event": "thinking_delta", "session_id": sid,
                        "data": {"thinking": delta.get("thinking", "")}}
            return None
        if et == "content_block_start":
            block = ev.get("content_block") or {}
            if block.get("type") == "tool_use":
                return {"event": "tool_use", "session_id": sid,
                        "data": {"id": block.get("id", ""),
                                 "name": block.get("name", ""),
                                 "input": block.get("input", {})}}
            return None
        if et in _IGNORED_STREAM_EVENTS:
            return None
        return None

    if t == "assistant":
        blocks = (d.get("message") or {}).get("content") or []
        for block in blocks:
            bt = block.get("type")
            if bt == "text":
                return {"event": "assistant_text", "session_id": sid,
                        "data": {"text": block.get("text", "")}}
            if bt == "tool_use":
                return {"event": "tool_use", "session_id": sid,
                        "data": {"id": block.get("id", ""),
                                 "name": block.get("name", ""),
                                 "input": block.get("input", {})}}
        # thinking 전용 블록은 스트리밍에서 이미 노출됨
        return None

    if t == "user":
        blocks = (d.get("message") or {}).get("content") or []
        for block in blocks:
            if block.get("type") == "tool_result":
                content = block.get("content")
                if isinstance(content, list):  # 블록 배열 형태 대응
                    content = "\n".join(
                        c.get("text", "") for c in content
                        if isinstance(c, dict) and c.get("type") == "text")
                return {"event": "tool_result", "session_id": sid,
                        "data": {"tool_use_id": block.get("tool_use_id", ""),
                                 "content": content or "",
                                 "is_error": block.get("is_error", False)}}
        return None

    if t == "result":
        return {"event": "result", "session_id": sid, "data": d}

    return None


def extract_choices(text: str) -> list[str]:
    """번호 매긴 선택지 추출 — 2개 이상일 때만 유효."""
    import re
    matches = re.findall(r"^\d+[.)]\s+(.+)$", text or "", re.MULTILINE)
    if len(matches) >= 2:
        return [m.strip() for m in matches]
    return []