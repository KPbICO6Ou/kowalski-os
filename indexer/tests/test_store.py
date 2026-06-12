import pytest

import kowindex.store
from kowindex.store import VectorStore

from .conftest import DIM, FakeEmbedder


def _populate(store: VectorStore, embedder: FakeEmbedder) -> None:
    voice = ["voice pipeline wake word", "wake word audio detection"]
    mail = ["mail imap smtp server", "mail credentials imap"]
    store.replace_file("/tmp/voice.md", 1.0, 100, voice, embedder.embed(voice))
    store.replace_file("/tmp/mail.md", 2.0, 200, mail, embedder.embed(mail))


def test_roundtrip_and_stats(store, fake_embedder):
    _populate(store, fake_embedder)
    assert store.stats() == {"files": 2, "chunks": 4}
    assert store.file_meta("/tmp/voice.md") == (1.0, 100)
    assert store.file_meta("/tmp/nope.md") is None


def test_search_ranks_matching_file_first(store, fake_embedder):
    _populate(store, fake_embedder)
    hits = store.search(fake_embedder.embed(["wake word voice"])[0], limit=4)
    assert hits[0]["path"] == "/tmp/voice.md"
    assert hits[0]["distance"] < hits[-1]["distance"]
    assert 0.0 <= hits[0]["distance"] <= 2.0


def test_replace_file_is_atomic_not_additive(store, fake_embedder):
    _populate(store, fake_embedder)
    texts = ["voice only one chunk now"]
    store.replace_file("/tmp/voice.md", 3.0, 50, texts, fake_embedder.embed(texts))
    assert store.stats() == {"files": 2, "chunks": 3}
    assert store.file_meta("/tmp/voice.md") == (3.0, 50)


def test_delete_file_removes_chunks(store, fake_embedder):
    _populate(store, fake_embedder)
    assert store.delete_file("/tmp/voice.md") == 2
    assert store.stats() == {"files": 1, "chunks": 2}
    hits = store.search(fake_embedder.embed(["wake word voice"])[0], limit=4)
    assert all(hit["path"] == "/tmp/mail.md" for hit in hits)


def test_dim_validated_on_reopen(tmp_path):
    db = tmp_path / "dim.db"
    VectorStore(db, dim=DIM).close()
    with pytest.raises(ValueError, match="dim"):
        VectorStore(db, dim=DIM + 1)
    reopened = VectorStore(db, dim=None)  # dim=None adopts the stored dimension
    assert reopened.dim == DIM
    reopened.close()


def test_wrong_vector_dim_rejected(store, fake_embedder):
    with pytest.raises(ValueError, match="dim"):
        store.replace_file("/tmp/x.md", 1.0, 1, ["text"], [[0.5] * (DIM + 3)])


def test_numpy_fallback_same_top_result(tmp_path, fake_embedder, monkeypatch):
    default_store = VectorStore(tmp_path / "default.db", dim=DIM)
    _populate(default_store, fake_embedder)
    query = fake_embedder.embed(["wake word voice"])[0]
    default_top = default_store.search(query, limit=2)[0]
    default_store.close()

    def boom(conn):
        raise OSError("simulated sqlite-vec load failure")

    monkeypatch.setattr(kowindex.store, "_load_sqlite_vec", boom)
    numpy_store = VectorStore(tmp_path / "numpy.db", dim=DIM)
    assert numpy_store.backend == "numpy"
    _populate(numpy_store, fake_embedder)
    numpy_top = numpy_store.search(query, limit=2)[0]
    numpy_store.close()

    assert numpy_top["path"] == default_top["path"]
    assert numpy_top["distance"] == pytest.approx(default_top["distance"], abs=1e-4)
