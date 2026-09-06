"""워크벤치 설정 영속화 — config.json (엔진 선택 유지)."""
import json

DEFAULTS = {"engine": "DIRECT", "ollama_model": "kimi-k2.7-code:cloud", "workspace": "workspace"}
_VALID_ENGINES = {"DIRECT", "OLLAMA"}


def load_config(path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            raise ValueError
    except (OSError, ValueError, json.JSONDecodeError):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in cfg.items() if k in DEFAULTS})
    if merged["engine"] not in _VALID_ENGINES:
        merged["engine"] = DEFAULTS["engine"]
    return merged


def save_config(path, cfg: dict) -> None:
    if cfg.get("engine") not in _VALID_ENGINES:
        raise ValueError(f"engine must be one of {sorted(_VALID_ENGINES)}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)