"""session_store.py 규격 테스트 — 세션별 턴 기록 저장/조회."""
import json

from session_store import append_turn, list_sessions, read_turns


def make_record(turn_no=1, prompt="안녕", cost=0.1, ts="2026-09-06T10:00:00"):
    return {"turn_no": turn_no, "prompt": prompt, "cost_usd": cost, "ts": ts,
            "events": [{"event": "assistant_text", "data": {"text": "응답"}}]}


# ---------- append_turn / read_turns ----------

def test_append_then_read_roundtrip(tmp_path):
    append_turn(tmp_path, "sid-1", make_record(turn_no=1, prompt="안녕"))
    append_turn(tmp_path, "sid-1", make_record(turn_no=2, prompt="다음", ts="2026-09-06T10:01:00"))
    turns = read_turns(tmp_path, "sid-1")
    assert len(turns) == 2
    assert turns[0]["prompt"] == "안녕"
    assert turns[1]["turn_no"] == 2


def test_read_missing_session_is_empty(tmp_path):
    assert read_turns(tmp_path, "nope") == []


def test_sessions_dir_created_on_demand(tmp_path):
    target = tmp_path / "sessions"
    append_turn(target, "sid-1", make_record())
    assert (target / "sid-1.jsonl").exists()


# ---------- list_sessions ----------

def test_list_sessions_summary(tmp_path):
    append_turn(tmp_path, "sid-1", make_record(turn_no=1, prompt="첫 질문", cost=0.1,
                                               ts="2026-09-06T10:00:00"))
    append_turn(tmp_path, "sid-1", make_record(turn_no=2, prompt="이어서", cost=0.2,
                                               ts="2026-09-06T10:01:00"))
    append_turn(tmp_path, "sid-2", make_record(turn_no=1, prompt="다른 세션", cost=0.05,
                                               ts="2026-09-06T11:00:00"))
    result = list_sessions(tmp_path)
    assert len(result) == 2
    by_sid = {s["sid"]: s for s in result}
    s1 = by_sid["sid-1"]
    assert s1["turns"] == 2
    assert abs(s1["total_cost"] - 0.3) < 1e-9
    assert s1["first_prompt"] == "첫 질문"
    assert s1["last_ts"] == "2026-09-06T10:01:00"


def test_list_sessions_newest_first(tmp_path):
    append_turn(tmp_path, "old", make_record(ts="2026-09-06T08:00:00"))
    append_turn(tmp_path, "new", make_record(ts="2026-09-06T12:00:00"))
    result = list_sessions(tmp_path)
    assert [s["sid"] for s in result] == ["new", "old"]


def test_list_sessions_empty_dir(tmp_path):
    assert list_sessions(tmp_path) == []


def test_list_sessions_skips_corrupt_lines(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text("{broken json\n", encoding="utf-8")
    assert list_sessions(tmp_path) == []  # 오류 없이 건너뜀


def test_list_sessions_ignores_raw_turn_logs(tmp_path):
    # sessions/turn_NNNN.jsonl 은 디버깅용 raw NDJSON 로그 — 세션이 아님
    raw = tmp_path / "turn_0001.jsonl"
    raw.write_text('{"type": "assistant"}\n', encoding="utf-8")
    append_turn(tmp_path, "sid-1", make_record())
    result = list_sessions(tmp_path)
    assert [s["sid"] for s in result] == ["sid-1"]