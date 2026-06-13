"""files.find hybrid-search tests: name + content (ripgrep) + semantic merge."""

import shutil
import sys
import types
from dataclasses import dataclass
from pathlib import Path

from kowalski.config import Config
from kowalski.tools.search import FileFindArgs, build_search_tools

REAL_WHICH = shutil.which


def make_config(root: Path) -> Config:
    return Config(
        {
            "KOW_ALLOWED_PATHS": str(root),
            "KOW_INDEX_DB": str(root / "index.db"),
            "OLLAMA_HOST": "http://127.0.0.1:11434",
            "KOW_EMBED_MODEL": "nomic-embed-text",
        }
    )


def make_tree(root: Path) -> None:
    # NAME match: file name contains "kowalski".
    (root / "kowalski_notes.txt").write_text("nothing relevant here\n")
    # CONTENT match: name unrelated, but body mentions "kowalski".
    (root / "diary.md").write_text("today I talked to kowalski about search\n")
    # Noise.
    (root / "unrelated.log").write_text("logs logs logs\n")


def force_no_rg(monkeypatch):
    """Pretend ripgrep is not installed (but keep fd/others honest)."""
    monkeypatch.setattr("shutil.which", lambda name: None if name == "rg" else REAL_WHICH(name))


def force_no_name_backend(monkeypatch):
    """Force pure-python name walk (no fd)."""
    monkeypatch.setattr(
        "shutil.which",
        lambda name: None if name == "fd" else REAL_WHICH(name),
    )


# ---- fake kowindex plumbing (same shape as test_tools_semantic) ----


@dataclass
class FakeHit:
    path: str
    score: float
    snippet: str
    chunk_index: int = 0
    mtime: str = ""


def install_fake_kowindex(monkeypatch, hits):
    class FakeIndex:
        def __init__(self, db_path, ollama_host=None, model=None):
            pass

        def stats(self):
            return {"files": 1, "chunks": 5}

        def search(self, query, limit):
            return hits[:limit]

    api = types.ModuleType("kowindex.api")
    api.SemanticIndex = FakeIndex
    pkg = types.ModuleType("kowindex")
    pkg.api = api
    monkeypatch.setitem(sys.modules, "kowindex", pkg)
    monkeypatch.setitem(sys.modules, "kowindex.api", api)


def disable_kowindex(monkeypatch):
    monkeypatch.setitem(sys.modules, "kowindex", None)
    monkeypatch.setitem(sys.modules, "kowindex.api", None)


# ---- tests ----


async def test_finds_both_name_and_content_matches(tmp_path: Path, monkeypatch):
    if not REAL_WHICH("rg"):
        import pytest

        pytest.skip("ripgrep not installed")
    disable_kowindex(monkeypatch)
    make_tree(tmp_path)
    tool = build_search_tools(make_config(tmp_path))[0]

    result = await tool.handler(FileFindArgs(query="kowalski", root=str(tmp_path)))
    assert result.ok
    paths = {Path(d["path"]).name for d in result.data}
    assert paths == {"kowalski_notes.txt", "diary.md"}

    by_name = {Path(d["path"]).name: d for d in result.data}
    # The name match should rank above the content-only match.
    assert by_name["kowalski_notes.txt"]["score"] > by_name["diary.md"]["score"]
    assert "name" in by_name["kowalski_notes.txt"]["sources"]
    assert "content" in by_name["diary.md"]["sources"]
    # Content hit captured a snippet.
    assert "kowalski" in by_name["diary.md"]["snippet"]


async def test_double_source_scores_higher_and_dedupes(tmp_path: Path, monkeypatch):
    if not REAL_WHICH("rg"):
        import pytest

        pytest.skip("ripgrep not installed")
    disable_kowindex(monkeypatch)
    # This file matches by BOTH name and content.
    (tmp_path / "kowalski.md").write_text("kowalski is great\n")
    # This file matches by content only.
    (tmp_path / "other.md").write_text("kowalski appears here too\n")
    tool = build_search_tools(make_config(tmp_path))[0]

    result = await tool.handler(FileFindArgs(query="kowalski", root=str(tmp_path)))
    assert result.ok
    # Deduped: each path appears once.
    assert len(result.data) == len({d["path"] for d in result.data})

    by_name = {Path(d["path"]).name: d for d in result.data}
    both = by_name["kowalski.md"]
    one = by_name["other.md"]
    assert set(both["sources"]) == {"name", "content"}
    assert both["score"] > one["score"]


async def test_content_source_skipped_when_rg_absent(tmp_path: Path, monkeypatch):
    disable_kowindex(monkeypatch)
    force_no_rg(monkeypatch)
    make_tree(tmp_path)
    tool = build_search_tools(make_config(tmp_path))[0]

    result = await tool.handler(FileFindArgs(query="kowalski", root=str(tmp_path)))
    assert result.ok
    # Only the name match survives; the content-only file is gone.
    paths = {Path(d["path"]).name for d in result.data}
    assert paths == {"kowalski_notes.txt"}
    assert all("content" not in d["sources"] for d in result.data)


async def test_name_match_via_python_walk(tmp_path: Path, monkeypatch):
    disable_kowindex(monkeypatch)
    force_no_name_backend(monkeypatch)  # no fd -> python walk
    make_tree(tmp_path)
    tool = build_search_tools(make_config(tmp_path))[0]
    result = await tool.handler(FileFindArgs(query="kowalski", root=str(tmp_path)))
    assert result.ok
    names = {Path(d["path"]).name for d in result.data}
    assert "kowalski_notes.txt" in names


async def test_semantic_source_merges_and_filters_by_root(tmp_path: Path, monkeypatch):
    force_no_rg(monkeypatch)  # isolate name + semantic
    target = tmp_path / "kowalski_notes.txt"
    make_tree(tmp_path)
    (tmp_path / "index.db").write_bytes(b"")
    hits = [
        FakeHit(str(target), 0.9, "semantic snippet about kowalski"),
        FakeHit("/outside/root/elsewhere.txt", 0.95, "should be filtered out"),
    ]
    install_fake_kowindex(monkeypatch, hits)
    tool = build_search_tools(make_config(tmp_path))[0]

    result = await tool.handler(FileFindArgs(query="kowalski", root=str(tmp_path)))
    assert result.ok
    by_name = {Path(d["path"]).name: d for d in result.data}
    # Outside-root semantic hit dropped.
    assert "elsewhere.txt" not in by_name
    # The on-disk name+semantic file gains both sources.
    assert set(by_name["kowalski_notes.txt"]["sources"]) == {"name", "semantic"}


async def test_semantic_skipped_when_unavailable(tmp_path: Path, monkeypatch):
    disable_kowindex(monkeypatch)
    force_no_rg(monkeypatch)
    make_tree(tmp_path)
    tool = build_search_tools(make_config(tmp_path))[0]
    result = await tool.handler(FileFindArgs(query="kowalski", root=str(tmp_path)))
    assert result.ok
    assert all("semantic" not in d["sources"] for d in result.data)


async def test_root_outside_allowlist_rejected(tmp_path: Path, monkeypatch):
    disable_kowindex(monkeypatch)
    inner = tmp_path / "inner"
    inner.mkdir()
    config = Config({"KOW_ALLOWED_PATHS": str(inner), "KOW_INDEX_DB": str(tmp_path / "i.db")})
    tool = build_search_tools(config)[0]
    result = await tool.handler(FileFindArgs(query="kowalski", root=str(tmp_path)))
    assert not result.ok
    assert "outside allowed" in result.content


async def test_no_matches(tmp_path: Path, monkeypatch):
    disable_kowindex(monkeypatch)
    make_tree(tmp_path)
    tool = build_search_tools(make_config(tmp_path))[0]
    result = await tool.handler(FileFindArgs(query="zzz-no-such-token", root=str(tmp_path)))
    assert result.ok
    assert result.data == []
    assert "No matches" in result.content


async def test_limit_respected(tmp_path: Path, monkeypatch):
    disable_kowindex(monkeypatch)
    force_no_rg(monkeypatch)
    for i in range(10):
        (tmp_path / f"kowalski_{i}.txt").write_text("x\n")
    tool = build_search_tools(make_config(tmp_path))[0]
    result = await tool.handler(FileFindArgs(query="kowalski", root=str(tmp_path), limit=3))
    assert result.ok
    assert len(result.data) == 3
