"""워크스페이스 파일 브라우저 — 경로 순회 방지가 최우선 제약.

모든 접근은 root(워크스페이스) 내부로 한정: 상대 경로만 허용하고,
resolve 결과가 root 밖이면 None (순회 시도).
"""
from pathlib import Path


def safe_resolve(root: Path, rel: str) -> Path | None:
    """상대 경로를 root 내부 절대 경로로 해석. 벗어나면 None."""
    rel = (rel or "").strip()
    if Path(rel).is_absolute():
        return None
    root_r = Path(root).resolve()
    target = (root_r / rel).resolve()
    if not target.is_relative_to(root_r):
        return None
    if not target.exists():
        return None
    return target


def list_dir(root: Path, rel: str) -> list[dict] | None:
    """디렉터리 목록 — dir 우선, 이름순. 잘못된 경로면 None."""
    target = safe_resolve(root, rel)
    if target is None or not target.is_dir():
        return None
    dirs, files = [], []
    for p in sorted(target.iterdir(), key=lambda x: x.name.lower()):
        if p.is_dir():
            dirs.append({"name": p.name, "type": "dir"})
        elif p.is_file():
            files.append({"name": p.name, "type": "file", "size": p.stat().st_size})
    return dirs + files


def read_file(root: Path, rel: str, limit: int = 100_000) -> dict | None:
    """텍스트 미리보기 — limit자 제한, 초과 시 truncated=True. 잘못된 경로면 None."""
    target = safe_resolve(root, rel)
    if target is None or not target.is_file():
        return None
    size = target.stat().st_size
    content = target.read_text(encoding="utf-8", errors="replace")[:limit]
    truncated = len(content) >= limit and size > limit
    return {"path": rel, "size": size, "truncated": truncated, "content": content}