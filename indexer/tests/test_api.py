from datetime import datetime

from kowindex.api import SemanticIndex
from kowindex.scanner import scan
from kowindex.store import VectorStore

from .conftest import DIM


def _build_index(tree, tmp_path, fake_embedder):
    db = tmp_path / "api.db"
    store = VectorStore(db, dim=DIM)
    scan([tree], store, fake_embedder)
    store.close()
    return db


def test_search_ranks_voice_file_first(tree, tmp_path, fake_embedder):
    db = _build_index(tree, tmp_path, fake_embedder)
    index = SemanticIndex(db, embedder=fake_embedder)
    hits = index.search("wake word voice", limit=5)
    assert hits, "expected at least one hit"
    assert hits[0].path == str(tree / "voice.md")
    assert hits[0].score > hits[-1].score or len(hits) == 1
    for hit in hits:
        assert 0.0 <= hit.score <= 1.0
        assert len(hit.snippet) <= 301
        assert hit.chunk_index >= 0
        datetime.fromisoformat(hit.mtime)  # valid ISO-8601
    index.close()


def test_stats_shape_and_counts(tree, tmp_path, fake_embedder):
    db = _build_index(tree, tmp_path, fake_embedder)
    index = SemanticIndex(db, model="nomic-embed-text")
    stats = index.stats()
    assert stats["files"] == 2
    assert stats["chunks"] >= 2
    assert stats["db_path"] == str(db)
    assert stats["model"] == "nomic-embed-text"
    assert stats["vec_backend"] in ("sqlite-vec", "numpy")
    index.close()


def test_stats_on_empty_index(tmp_path):
    index = SemanticIndex(tmp_path / "empty.db")
    stats = index.stats()
    assert stats["files"] == 0
    assert stats["chunks"] == 0
    index.close()
