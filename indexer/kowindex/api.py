"""Public API for the semantic index: SemanticIndex + SearchHit (consumed by kow-core)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .embedder import Embedder, OllamaEmbedder
from .store import VectorStore

SNIPPET_CHARS = 300


@dataclass
class SearchHit:
    path: str
    score: float        # similarity in [0..1], higher = better (1 - cosine distance)
    snippet: str        # chunk text trimmed to ~300 chars
    chunk_index: int
    mtime: str          # ISO-8601


def _snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    flattened = " ".join(text.split())
    if len(flattened) <= limit:
        return flattened
    return flattened[: limit - 1].rstrip() + "…"


class SemanticIndex:
    """Read/search facade over an existing index database.

    The embedder is created lazily (stats() works without a running Ollama);
    tests inject a fake via the optional `embedder` keyword.
    """

    def __init__(
        self,
        db_path: Path | str,
        ollama_host: str = "http://127.0.0.1:11434",
        model: str = "nomic-embed-text",
        embedder: Embedder | None = None,
    ):
        self.db_path = Path(db_path).expanduser()
        self.model = model
        # dim=None: adopt whatever dimension the database was created with
        self.store = VectorStore(self.db_path, dim=None)
        self._embedder = embedder
        self._ollama_host = ollama_host

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = OllamaEmbedder(self._ollama_host, self.model)
        return self._embedder

    def search(self, query: str, limit: int = 10) -> list[SearchHit]:
        vector = self.embedder.embed([query])[0]
        hits = []
        for row in self.store.search(vector, limit=limit):
            score = max(0.0, min(1.0, 1.0 - row["distance"]))
            mtime = datetime.fromtimestamp(row["mtime"] or 0.0, tz=UTC).isoformat()
            hits.append(
                SearchHit(
                    path=row["path"],
                    score=score,
                    snippet=_snippet(row["text"]),
                    chunk_index=row["chunk_index"],
                    mtime=mtime,
                )
            )
        return hits

    def stats(self) -> dict:
        counts = self.store.stats()
        return {
            "files": counts["files"],
            "chunks": counts["chunks"],
            "db_path": str(self.db_path),
            "model": self.model,
            "vec_backend": self.store.backend,
        }

    def close(self) -> None:
        self.store.close()
