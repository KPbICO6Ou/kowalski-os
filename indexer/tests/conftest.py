"""Shared fixtures: deterministic FakeEmbedder (no network) and a sample file tree."""

from __future__ import annotations

import math
import os
import re
import zlib

import pytest

from kowindex.store import VectorStore

# Known words map to dedicated orthogonal axes; everything else lands softly on
# the spare axes via crc32, so unrelated texts stay nearly orthogonal.
VOCAB = [
    "voice", "pipeline", "wake", "word", "audio",
    "mail", "imap", "smtp", "server", "credentials",
    "python", "index",
]
DIM = 16


class FakeEmbedder:
    """Deterministic keyword-based embeddings; counts calls for incremental tests."""

    dim = DIM

    def __init__(self):
        self.embed_calls = 0
        self.texts_embedded = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls += 1
        self.texts_embedded += len(texts)
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * DIM
        for word in re.findall(r"[a-zA-Z]+", text.lower()):
            if word in VOCAB:
                vector[VOCAB.index(word)] += 1.0
            else:
                vector[len(VOCAB) + zlib.crc32(word.encode()) % (DIM - len(VOCAB))] += 0.05
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


VOICE_TEXT = (
    "The voice pipeline listens for the wake word.\n\n"
    "Wake word detection runs on short audio frames; the voice pipeline then\n"
    "streams audio to the recognizer.\n"
)
MAIL_TEXT = (
    "Mail synchronisation uses IMAP to fetch messages and SMTP to send them.\n\n"
    "The mail server credentials live in the keyring; IMAP folders sync on a timer.\n"
)


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def tree(tmp_path):
    """Tmp tree: a voice doc, a mail doc, plus files that must be skipped."""
    root = tmp_path / "docs"
    root.mkdir()
    (root / "voice.md").write_text(VOICE_TEXT)
    (root / "mail.md").write_text(MAIL_TEXT)
    (root / "blob.bin").write_bytes(os.urandom(256))  # unknown extension
    (root / "huge.txt").write_text("x" * (2 * 1024 * 1024 + 1))  # over the 2 MB cap
    hidden = root / ".cache"
    hidden.mkdir()
    (hidden / "notes.md").write_text("hidden voice wake word")
    vendored = root / "node_modules"
    vendored.mkdir()
    (vendored / "pkg.md").write_text("vendored mail imap")
    return root


@pytest.fixture
def store(tmp_path) -> VectorStore:
    vector_store = VectorStore(tmp_path / "index.db", dim=DIM)
    yield vector_store
    vector_store.close()
