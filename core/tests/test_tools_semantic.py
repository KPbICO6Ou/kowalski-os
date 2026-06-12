import sys
import types
from dataclasses import dataclass
from pathlib import Path

from kowalski.config import Config
from kowalski.tools.files import SemanticSearchArgs, build_semantic_tools


@dataclass
class FakeHit:
    path: str
    score: float
    snippet: str
    chunk_index: int
    mtime: str


HITS = [
    FakeHit("/home/u/notes/llm.md", 0.87, "transformers and attention", 0, "2026-06-01T10:00:00"),
    FakeHit("/home/u/docs/talk.txt", 0.61, "a talk about embeddings", 2, "2026-05-20T08:30:00"),
]


def make_config(tmp_path: Path) -> Config:
    return Config(
        {
            "KOW_INDEX_DB": str(tmp_path / "index.db"),
            "OLLAMA_HOST": "http://127.0.0.1:11434",
            "KOW_EMBED_MODEL": "nomic-embed-text",
        }
    )


def install_fake_kowindex(monkeypatch, index_cls) -> None:
    api = types.ModuleType("kowindex.api")
    api.SemanticIndex = index_cls
    api.SearchHit = FakeHit
    pkg = types.ModuleType("kowindex")
    pkg.api = api
    monkeypatch.setitem(sys.modules, "kowindex", pkg)
    monkeypatch.setitem(sys.modules, "kowindex.api", api)


class FakeIndex:
    last_init: tuple | None = None

    def __init__(self, db_path, ollama_host=None, model=None):
        FakeIndex.last_init = (db_path, ollama_host, model)

    def stats(self):
        return {"files": 2, "chunks": 10}

    def search(self, query, limit):
        return HITS[:limit]


async def test_semantic_search_formats_hits(tmp_path: Path, monkeypatch):
    install_fake_kowindex(monkeypatch, FakeIndex)
    config = make_config(tmp_path)
    (tmp_path / "index.db").write_bytes(b"")
    tool = build_semantic_tools(config)[0]
    assert tool.name == "files.search_semantic"

    result = await tool.handler(SemanticSearchArgs(query="machine learning notes"))
    assert result.ok
    lines = result.content.splitlines()
    assert "semantic matches" in lines[0]
    assert lines[1] == "score=0.87  /home/u/notes/llm.md  — transformers and attention"
    assert lines[2] == "score=0.61  /home/u/docs/talk.txt  — a talk about embeddings"
    assert result.data[0]["path"] == "/home/u/notes/llm.md"
    assert result.data[0]["chunk_index"] == 0
    assert result.data[1]["score"] == 0.61
    # the index was constructed from config values
    db_path, host, model = FakeIndex.last_init
    assert db_path == tmp_path / "index.db"
    assert host == "http://127.0.0.1:11434"
    assert model == "nomic-embed-text"


async def test_semantic_search_limit_respected(tmp_path: Path, monkeypatch):
    install_fake_kowindex(monkeypatch, FakeIndex)
    config = make_config(tmp_path)
    (tmp_path / "index.db").write_bytes(b"")
    tool = build_semantic_tools(config)[0]
    result = await tool.handler(SemanticSearchArgs(query="anything", limit=1))
    assert result.ok
    assert len(result.data) == 1


async def test_semantic_search_missing_db(tmp_path: Path, monkeypatch):
    install_fake_kowindex(monkeypatch, FakeIndex)
    config = make_config(tmp_path)  # no index.db on disk
    tool = build_semantic_tools(config)[0]
    result = await tool.handler(SemanticSearchArgs(query="anything"))
    assert result.ok
    assert "kow-index index" in result.content
    assert result.data == []


async def test_semantic_search_zero_chunks(tmp_path: Path, monkeypatch):
    class EmptyIndex(FakeIndex):
        def stats(self):
            return {"files": 0, "chunks": 0}

    install_fake_kowindex(monkeypatch, EmptyIndex)
    config = make_config(tmp_path)
    (tmp_path / "index.db").write_bytes(b"")
    tool = build_semantic_tools(config)[0]
    result = await tool.handler(SemanticSearchArgs(query="anything"))
    assert result.ok
    assert "kow-index index" in result.content
    assert result.data == []


async def test_semantic_search_not_installed(tmp_path: Path, monkeypatch):
    # sys.modules[name] = None makes `import kowindex.api` raise ImportError
    monkeypatch.setitem(sys.modules, "kowindex", None)
    monkeypatch.setitem(sys.modules, "kowindex.api", None)
    tool = build_semantic_tools(make_config(tmp_path))[0]
    result = await tool.handler(SemanticSearchArgs(query="anything"))
    assert not result.ok
    assert "pip install -e indexer" in result.content


async def test_semantic_search_backend_error(tmp_path: Path, monkeypatch):
    class BrokenIndex(FakeIndex):
        def search(self, query, limit):
            raise RuntimeError("ollama is down")

    install_fake_kowindex(monkeypatch, BrokenIndex)
    config = make_config(tmp_path)
    (tmp_path / "index.db").write_bytes(b"")
    tool = build_semantic_tools(config)[0]
    result = await tool.handler(SemanticSearchArgs(query="anything"))
    assert not result.ok
    assert "ollama is down" in result.content
