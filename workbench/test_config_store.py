"""config_store.py 규격 테스트 — 엔진 선택 영속화(사용자 요구: 한번 선택하면 유지)."""
import json
import pytest
from config_store import load_config, save_config

DEFAULTS = {"engine": "DIRECT", "ollama_model": "kimi-k2.7-code:cloud", "workspace": "workspace",
            "max_budget_usd": None}


def test_missing_file_returns_defaults(tmp_path):
    assert load_config(tmp_path / "nope.json") == DEFAULTS


def test_corrupt_file_returns_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_config(p) == DEFAULTS


def test_existing_file_preserves_engine(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"engine": "OLLAMA", "ollama_model": "kimi-k-code"}), encoding="utf-8")
    cfg = load_config(p)
    assert cfg["engine"] == "OLLAMA"
    assert cfg["ollama_model"] == "kimi-k-code"
    assert cfg["workspace"] == "workspace"  # 누락 키는 기본값 보강


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "config.json"
    save_config(p, {"engine": "OLLAMA", "ollama_model": "custom-model", "workspace": "workspace"})
    assert load_config(p)["engine"] == "OLLAMA"


def test_save_rejects_invalid_engine(tmp_path):
    with pytest.raises(ValueError):
        save_config(tmp_path / "config.json", {"engine": "BOGUS", "ollama_model": "m", "workspace": "w"})


# ---------- max_budget_usd (#17 budget 옵션) ----------

def test_budget_missing_key_defaults_to_none(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"engine": "DIRECT"}), encoding="utf-8")
    assert load_config(p)["max_budget_usd"] is None


def test_budget_roundtrip(tmp_path):
    p = tmp_path / "config.json"
    save_config(p, {"engine": "DIRECT", "ollama_model": "m", "workspace": "w",
                    "max_budget_usd": 0.5})
    assert load_config(p)["max_budget_usd"] == 0.5


def test_budget_invalid_type_normalized_to_none(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"engine": "DIRECT", "max_budget_usd": "many"}), encoding="utf-8")
    assert load_config(p)["max_budget_usd"] is None


def test_budget_zero_means_off(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"engine": "DIRECT", "max_budget_usd": 0}), encoding="utf-8")
    assert load_config(p)["max_budget_usd"] == 0