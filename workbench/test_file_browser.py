"""file_browser.py 규격 테스트 — 경로 순회 방지가 핵심."""
from file_browser import list_dir, read_file, safe_resolve


def make_tree(root):
    (root / "sub").mkdir()
    (root / "sub" / "deep.txt").write_text("deep", encoding="utf-8")
    (root / "hello.txt").write_text("안녕 워크스페이스", encoding="utf-8")
    (root / "big.txt").write_text("가" * 300, encoding="utf-8")


# ---------- safe_resolve ----------

def test_resolve_root(tmp_path):
    assert safe_resolve(tmp_path, "") == tmp_path


def test_resolve_within(tmp_path):
    make_tree(tmp_path)
    p = safe_resolve(tmp_path, "sub/deep.txt")
    assert p == tmp_path / "sub" / "deep.txt"


def test_resolve_rejects_parent_traversal(tmp_path):
    assert safe_resolve(tmp_path, "../outside.txt") is None
    assert safe_resolve(tmp_path, "sub/../../escape.txt") is None


def test_resolve_rejects_absolute_path(tmp_path):
    assert safe_resolve(tmp_path, "C:/Windows/system32") is None
    assert safe_resolve(tmp_path, "/etc/passwd") is None


def test_resolve_rejects_missing_path(tmp_path):
    assert safe_resolve(tmp_path, "no/such/file.txt") is None


# ---------- list_dir ----------

def test_list_dir_entries(tmp_path):
    make_tree(tmp_path)
    entries = list_dir(tmp_path, "")
    names = [e["name"] for e in entries]
    types = {e["name"]: e["type"] for e in entries}
    assert "sub" in names and "hello.txt" in names and "big.txt" in names
    assert types["sub"] == "dir"
    assert types["hello.txt"] == "file"


def test_list_dir_dirs_first(tmp_path):
    make_tree(tmp_path)
    entries = list_dir(tmp_path, "")
    assert [e["type"] for e in entries] == sorted(
        [e["type"] for e in entries], key=lambda t: t != "dir")


def test_list_dir_subdirectory(tmp_path):
    make_tree(tmp_path)
    entries = list_dir(tmp_path, "sub")
    assert entries == [{"name": "deep.txt", "type": "file",
                        "size": 4}]


def test_list_dir_invalid_path_is_none(tmp_path):
    assert list_dir(tmp_path, "../..") is None
    assert list_dir(tmp_path, "C:/Windows") is None


def test_list_dir_missing_dir_is_none(tmp_path):
    assert list_dir(tmp_path, "nope") is None


# ---------- read_file ----------

def test_read_file_text(tmp_path):
    make_tree(tmp_path)
    r = read_file(tmp_path, "hello.txt")
    assert r["content"] == "안녕 워크스페이스"
    assert r["truncated"] is False


def test_read_file_truncates(tmp_path):
    make_tree(tmp_path)
    r = read_file(tmp_path, "big.txt", limit=100)
    assert len(r["content"]) == 100
    assert r["truncated"] is True


def test_read_file_invalid_path_is_none(tmp_path):
    assert read_file(tmp_path, "../secret.txt") is None
    assert read_file(tmp_path, "no/such.txt") is None