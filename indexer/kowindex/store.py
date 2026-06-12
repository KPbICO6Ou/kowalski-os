"""SQLite vector store: chunks + float32 embeddings, sqlite-vec KNN with numpy fallback.

Embeddings are L2-normalized before storage, so the sqlite-vec L2 distance maps
to cosine distance as d^2 / 2 and the numpy fallback is a plain dot product.
The embedding dimension is fixed at creation, persisted in the meta table, and
validated on reopen (pass dim=None to adopt whatever the database was built with).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    mtime REAL,
    size INTEGER,
    chunk_count INTEGER
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    chunk_index INTEGER,
    text TEXT NOT NULL,
    embedding BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
"""

DEFAULT_DIM = 768


def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
    """Load the sqlite-vec extension; raises on any failure (tests monkeypatch this)."""
    import sqlite_vec

    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)


class VectorStore:
    """Embedding store with two interchangeable KNN backends: sqlite-vec or numpy."""

    def __init__(self, db_path: Path | str, dim: int | None = DEFAULT_DIM):
        path = Path(db_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = path
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row

        self.backend = "numpy"
        try:
            _load_sqlite_vec(self.conn)
            self.backend = "sqlite-vec"
        except Exception:  # extension loading fails on some macOS pythons
            pass

        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.dim = self._resolve_dim(dim)
        if self.backend == "sqlite-vec":
            self._init_vec_table()
        self.conn.commit()

    def _resolve_dim(self, dim: int | None) -> int:
        row = self.conn.execute("SELECT value FROM meta WHERE key = 'dim'").fetchone()
        stored = int(row["value"]) if row else None
        if stored is not None:
            if dim is not None and dim != stored:
                raise ValueError(
                    f"index at {self.db_path} was built with dim={stored}, got dim={dim}; "
                    "delete the database to re-index with a different model"
                )
            return stored
        resolved = dim if dim is not None else DEFAULT_DIM
        self.conn.execute("INSERT INTO meta (key, value) VALUES ('dim', ?)", (str(resolved),))
        return resolved

    def _init_vec_table(self) -> None:
        """Create the vec0 shadow table (rowid = chunks.id) and backfill missing rows."""
        self.conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(embedding float[{self.dim}])"
        )
        self.conn.execute(
            "INSERT INTO vec_chunks (rowid, embedding) "
            "SELECT id, embedding FROM chunks WHERE id NOT IN (SELECT rowid FROM vec_chunks)"
        )

    def _to_blob(self, vector: list[float]) -> bytes:
        arr = np.asarray(vector, dtype="<f4")
        if arr.shape != (self.dim,):
            raise ValueError(f"expected embedding of dim {self.dim}, got shape {arr.shape}")
        norm = float(np.linalg.norm(arr))
        if norm > 0:
            arr = arr / norm
        return arr.astype("<f4").tobytes()

    # -- files / chunks ------------------------------------------------------

    def file_meta(self, path: str) -> tuple[float, int] | None:
        row = self.conn.execute("SELECT mtime, size FROM files WHERE path = ?", (path,)).fetchone()
        return (row["mtime"], row["size"]) if row else None

    def all_files(self) -> dict[str, tuple[float, int]]:
        rows = self.conn.execute("SELECT path, mtime, size FROM files").fetchall()
        return {row["path"]: (row["mtime"], row["size"]) for row in rows}

    def replace_file(
        self,
        path: str,
        mtime: float,
        size: int,
        texts: list[str],
        embeddings: list[list[float]],
    ) -> int:
        """Atomically replace a file's chunks (and vec rows) with a fresh set."""
        if len(texts) != len(embeddings):
            raise ValueError("texts and embeddings length mismatch")
        with self.conn:
            self._delete_chunks(path)
            for index, (text, embedding) in enumerate(zip(texts, embeddings, strict=True)):
                blob = self._to_blob(embedding)
                cursor = self.conn.execute(
                    "INSERT INTO chunks (path, chunk_index, text, embedding) VALUES (?, ?, ?, ?)",
                    (path, index, text, blob),
                )
                if self.backend == "sqlite-vec":
                    self.conn.execute(
                        "INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)",
                        (cursor.lastrowid, blob),
                    )
            self.conn.execute(
                "INSERT OR REPLACE INTO files (path, mtime, size, chunk_count) "
                "VALUES (?, ?, ?, ?)",
                (path, mtime, size, len(texts)),
            )
        return len(texts)

    def delete_file(self, path: str) -> int:
        """Remove a file and its chunks; returns the number of chunks removed."""
        with self.conn:
            removed = self._delete_chunks(path)
            self.conn.execute("DELETE FROM files WHERE path = ?", (path,))
        return removed

    def _delete_chunks(self, path: str) -> int:
        if self.backend == "sqlite-vec":
            self.conn.execute(
                "DELETE FROM vec_chunks WHERE rowid IN (SELECT id FROM chunks WHERE path = ?)",
                (path,),
            )
        return self.conn.execute("DELETE FROM chunks WHERE path = ?", (path,)).rowcount

    # -- search --------------------------------------------------------------

    def search(self, vector: list[float], limit: int = 10) -> list[dict[str, Any]]:
        """KNN over chunks; returns dicts with path/chunk_index/text/mtime/distance (cosine)."""
        empty = self.conn.execute("SELECT 1 FROM chunks LIMIT 1").fetchone() is None
        if empty:
            return []
        query = self._to_blob(vector)
        if self.backend == "sqlite-vec":
            return self._search_vec(query, limit)
        return self._search_numpy(query, limit)

    def _search_vec(self, query: bytes, limit: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT c.path, c.chunk_index, c.text, f.mtime, v.distance FROM "
            "(SELECT rowid, distance FROM vec_chunks WHERE embedding MATCH ? "
            f"ORDER BY distance LIMIT {int(limit)}) v "
            "JOIN chunks c ON c.id = v.rowid "
            "JOIN files f ON f.path = c.path "
            "ORDER BY v.distance",
            (query,),
        ).fetchall()
        # L2 distance over unit vectors -> cosine distance = d^2 / 2
        return [
            {
                "path": row["path"],
                "chunk_index": row["chunk_index"],
                "text": row["text"],
                "mtime": row["mtime"],
                "distance": (row["distance"] ** 2) / 2.0,
            }
            for row in rows
        ]

    def _search_numpy(self, query: bytes, limit: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT c.path, c.chunk_index, c.text, c.embedding, f.mtime "
            "FROM chunks c JOIN files f ON f.path = c.path"
        ).fetchall()
        if not rows:
            return []
        matrix = np.frombuffer(b"".join(row["embedding"] for row in rows), dtype="<f4")
        matrix = matrix.reshape(len(rows), self.dim)
        similarities = matrix @ np.frombuffer(query, dtype="<f4")
        order = np.argsort(-similarities)[:limit]
        return [
            {
                "path": rows[i]["path"],
                "chunk_index": rows[i]["chunk_index"],
                "text": rows[i]["text"],
                "mtime": rows[i]["mtime"],
                "distance": float(1.0 - similarities[i]),
            }
            for i in order
        ]

    # -- misc ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        files = self.conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
        chunks = self.conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
        return {"files": files, "chunks": chunks}

    def close(self) -> None:
        self.conn.close()
