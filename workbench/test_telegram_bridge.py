"""telegram_bridge.py 순수 로직 테스트 — 외부 API 호출 제외."""
import pytest
from telegram_bridge import load_token, make_keyboard, split_for_telegram


# ---------- load_token ----------

def test_load_token_trims(tmp_path):
    p = tmp_path / ".telegram_token"
    p.write_text("123456:ABC-DEF\n", encoding="utf-8")
    assert load_token(p) == "123456:ABC-DEF"


def test_load_token_missing_raises(tmp_path):
    with pytest.raises(RuntimeError, match="token"):
        load_token(tmp_path / "nope")


# ---------- make_keyboard ----------

def test_keyboard_two_choices():
    kb = make_keyboard(["계속 진행", "중단"])
    buttons = kb["inline_keyboard"]
    assert len(buttons) == 2
    assert buttons[0][0]["text"] == "계속 진행"
    assert buttons[0][0]["callback_data"] == "choice:0"
    assert buttons[1][0]["callback_data"] == "choice:1"


def test_keyboard_empty():
    assert make_keyboard([]) is None


# ---------- split_for_telegram ----------

def test_split_short_text_single_piece():
    assert split_for_telegram("안녕하세요") == ["안녕하세요"]


def test_split_long_text_respects_limit():
    text = "가" * 10000
    parts = split_for_telegram(text, limit=4096)
    assert len(parts) > 1
    assert all(len(p) <= 4096 for p in parts)
    assert "".join(parts) == text  # 내용 손실 없음


# ---------- 턴 응답 조립 ----------

def test_build_reply_from_events():
    from telegram_bridge import build_reply
    events = [
        {"event": "tool_use", "data": {"id": "c1", "name": "Bash",
                                       "input": {"command": "pwd"}}},
        {"event": "tool_result", "data": {"tool_use_id": "c1",
                                          "content": "/i/progwork", "is_error": False}},
        {"event": "assistant_text", "data": {"text": "현재 경로입니다."}},
        {"event": "result", "data": {"is_error": False, "total_cost_usd": 0.2}},
    ]
    reply, choices = build_reply(events)
    assert "현재 경로입니다." in reply
    assert choices == []  # 선택지 없음


def test_build_reply_extract_choices():
    from telegram_bridge import build_reply
    events = [
        {"event": "assistant_text", "data": {"text": "방법을 골라주세요\n1. Docker 사용\n2. 로컬 실행"}},
    ]
    reply, choices = build_reply(events)
    assert choices == ["Docker 사용", "로컬 실행"]


def test_build_reply_error_tool_result_visible():
    from telegram_bridge import build_reply
    events = [
        {"event": "tool_result", "data": {"tool_use_id": "c1",
                                          "content": "you haven't granted it yet.",
                                          "is_error": True}},
        {"event": "assistant_text", "data": {"text": "권한이 거부되었습니다."}},
    ]
    reply, _ = build_reply(events)
    assert "거부" in reply
    assert "⚠️" in reply  # 거부 표식