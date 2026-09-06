"""parser.py 규격 테스트 — 실측 dump(dump_text.jsonl / dump_tool.jsonl) 기반."""
import pytest
from parser import parse_line, extract_choices

SID_A = "3ce4bb2a-f057-43e3-9885-438e493f89ec"  # dump_text.jsonl
SID_B = "1d653acd-e724-4871-8ef5-f617ed87f30b"  # dump_tool.jsonl


def load_dump(name: str) -> list[str]:
    with open(name, encoding="utf-8") as f:
        return [l.rstrip("\n") for l in f]


# ---------- init ----------

def test_init_event():
    line = load_dump("dump_text.jsonl")[2]
    ev = parse_line(line)
    assert ev["event"] == "init"
    assert ev["session_id"] == SID_A
    assert ev["data"]["model"] == "glm-5.3-flash:cloud"
    assert ev["data"]["permissionMode"] == "default"


# ---------- stream_event 델타 ----------

def test_text_delta():
    line = '{"type": "stream_event", "event": {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "OK"}}, "session_id": "%s", "parent_tool_use_id": null, "uuid": "u"}' % SID_A
    ev = parse_line(line)
    assert ev["event"] == "text_delta"
    assert ev["session_id"] == SID_A
    assert ev["data"]["text"] == "OK"


def test_thinking_delta():
    line = load_dump("dump_text.jsonl")[6]
    ev = parse_line(line)
    assert ev["event"] == "thinking_delta"
    assert ev["session_id"] == SID_A
    assert ev["data"]["thinking"] == "The"


def test_message_start_is_ignored():
    line = load_dump("dump_text.jsonl")[4]
    assert parse_line(line) is None


def test_content_block_stop_is_ignored():
    line = '{"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}, "session_id": "%s"}' % SID_A
    assert parse_line(line) is None


def test_message_delta_and_stop_are_ignored():
    md = '{"type": "stream_event", "event": {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}, "session_id": "%s"}' % SID_A
    ms = '{"type": "stream_event", "event": {"type": "message_stop"}, "session_id": "%s"}' % SID_A
    assert parse_line(md) is None
    assert parse_line(ms) is None


def test_tool_use_from_content_block_start():
    line = ('{"type": "stream_event", "event": {"type": "content_block_start", "index": 0, '
            '"content_block": {"type": "tool_use", "id": "call_x", "name": "Write", "input": {}}}, '
            '"session_id": "%s"}' % SID_B)
    ev = parse_line(line)
    assert ev["event"] == "tool_use"
    assert ev["data"]["id"] == "call_x"
    assert ev["data"]["name"] == "Write"


# ---------- assistant 최종 메시지 ----------

def test_assistant_text_block():
    raw = ('{"type": "assistant", "message": {"id": "m", "role": "assistant", "content": '
           '[{"type": "text", "text": "OK"}]}, "session_id": "%s"}' % SID_A)
    ev = parse_line(raw)
    assert ev["event"] == "assistant_text"
    assert ev["session_id"] == SID_A
    assert ev["data"]["text"] == "OK"


def test_assistant_tool_use_block():
    line = load_dump("dump_tool.jsonl")[41]
    ev = parse_line(line)
    assert ev["event"] == "tool_use"
    assert ev["session_id"] == SID_B
    assert ev["data"]["id"] == "call_4qhlgmq8"
    assert ev["data"]["name"] == "Write"
    assert ev["data"]["input"]["file_path"].endswith("wb_probe.txt")


def test_assistant_thinking_only_is_ignored():
    line = load_dump("dump_text.jsonl")[30]
    assert parse_line(line) is None


# ---------- user tool_result ----------

def test_tool_result_deny():
    line = load_dump("dump_tool.jsonl")[45]
    ev = parse_line(line)
    assert ev["event"] == "tool_result"
    assert ev["session_id"] == SID_B
    assert ev["data"]["is_error"] is True
    assert ev["data"]["tool_use_id"] == "call_4qhlgmq8"
    assert "haven't granted it yet" in ev["data"]["content"]


# ---------- result ----------

def test_result_event():
    line = load_dump("dump_tool.jsonl")[115]
    ev = parse_line(line)
    assert ev["event"] == "result"
    assert ev["session_id"] == SID_B
    assert ev["data"]["is_error"] is False
    assert ev["data"]["total_cost_usd"] > 0
    assert ev["data"]["num_turns"] == 2


# ---------- 무시/기타 ----------

def test_hooks_and_status_are_ignored():
    dump = load_dump("dump_text.jsonl")
    assert parse_line(dump[0]) is None  # hook_started
    assert parse_line(dump[1]) is None  # hook_response
    assert parse_line(dump[3]) is None  # status


def test_unknown_type_is_ignored():
    assert parse_line('{"type": "something_new", "x": 1}') is None


def test_non_json_becomes_raw():
    ev = parse_line("Warning: deprecation notice")
    assert ev["event"] == "raw"
    assert ev["data"] == "Warning: deprecation notice"


def test_blank_line_is_ignored():
    assert parse_line("") is None
    assert parse_line("   ") is None


# ---------- extract_choices ----------

def test_choices_two_matches():
    assert extract_choices("1. 계속 진행\n2. 중단") == ["계속 진행", "중단"]


def test_choices_paren_style():
    assert extract_choices("1) 가다\n2) 멈추다") == ["가다", "멈추다"]


def test_single_numbered_line_is_not_choices():
    assert extract_choices("1. 하나뿐인 항목") == []


def test_no_choices():
    assert extract_choices("1 + 1 = 2 입니다") == []