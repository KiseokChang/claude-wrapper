"""server.build_cmd 규격 테스트 — budget 플래그와 엔진별 명령 형태."""
import pytest
from server import build_cmd

CFG_DIRECT = {"engine": "DIRECT", "ollama_model": "kimi-k2.7-code:cloud",
              "workspace": "workspace", "max_budget_usd": None}


def test_direct_base_shape():
    cmd = build_cmd("hi", CFG_DIRECT, None, skip_permissions=False)
    assert cmd[0].lower().endswith(("claude.cmd", "claude"))
    assert "-p" in cmd and "hi" in cmd
    assert "--max-budget-usd" not in cmd


def test_budget_flag_present_when_set():
    cfg = dict(CFG_DIRECT, max_budget_usd=0.5)
    cmd = build_cmd("hi", cfg, None, skip_permissions=False)
    i = cmd.index("--max-budget-usd")
    assert cmd[i + 1] == "0.5"


def test_budget_flag_absent_when_zero():
    cfg = dict(CFG_DIRECT, max_budget_usd=0)
    assert "--max-budget-usd" not in build_cmd("hi", cfg, None, False)


def test_ollama_budget_after_separator():
    cfg = dict(CFG_DIRECT, engine="OLLAMA", max_budget_usd=1.25)
    cmd = build_cmd("hi", cfg, None, False)
    assert "--" in cmd  # ollama launch 구분자
    i = cmd.index("--max-budget-usd")
    assert cmd[i + 1] == "1.25"
    assert cmd.index("--") < i  # 구분자 뒤 tail에 붙음