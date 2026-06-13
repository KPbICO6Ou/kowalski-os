"""MemoryStore: semantic long-term memories + a key/value user profile.

Runs its own CREATE TABLE IF NOT EXISTS so it does not depend on store.py's
SCHEMA. Embeddings are stored as little-endian float32 BLOBs; cosine similarity
is computed in pure Python (no numpy).
"""

from __future__ import annotations

import math
from array import array
from typing import Any

from ..store import Store

_NOW = "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"

MEMORY_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT {_NOW},
    text TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    embedding BLOB NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT {_NOW}
);
"""


def pack_vector(vector: list[float]) -> bytes:
    """Pack a float vector into little-endian float32 bytes."""
    arr = array("f", (float(x) for x in vector))
    if array("f", [1.0]).tobytes() != _LE_ONE:
        arr.byteswap()  # normalize to little-endian on big-endian hosts
    return arr.tobytes()


def unpack_vector(blob: bytes) -> list[float]:
    """Unpack little-endian float32 bytes into a list of floats."""
    if not blob:
        return []
    arr = array("f")
    arr.frombytes(blob)
    if array("f", [1.0]).tobytes() != _LE_ONE:
        arr.byteswap()
    return list(arr)


_LE_ONE = b"\x00\x00\x80\x3f"  # float32 1.0, little-endian


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; returns 0.0 for empty or zero-norm vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class MemoryStore:
    def __init__(self, store: Store):
        self.store = store
        self.conn = store.conn
        self.conn.executescript(MEMORY_SCHEMA)
        self.conn.commit()

    # --- semantic memories ------------------------------------------------

    def remember(self, text: str, tags: list[str], embedding: list[float]) -> int:
        cur = self.conn.execute(
            "INSERT INTO memories (text, tags, embedding) VALUES (?, ?, ?)",
            (text, ",".join(tags), pack_vector(embedding)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def recall(self, query_embedding: list[float], k: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, text, tags, embedding FROM memories"
        ).fetchall()
        scored: list[dict[str, Any]] = []
        for row in rows:
            score = cosine(query_embedding, unpack_vector(row["embedding"]))
            scored.append(
                {
                    "id": row["id"],
                    "text": row["text"],
                    "tags": _split_tags(row["tags"]),
                    "score": score,
                }
            )
        scored.sort(key=lambda m: m["score"], reverse=True)
        return scored[: max(0, k)]

    def forget(self, memory_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def list_memories(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, ts, text, tags FROM memories ORDER BY id"
        ).fetchall()
        return [
            {
                "id": row["id"],
                "ts": row["ts"],
                "text": row["text"],
                "tags": _split_tags(row["tags"]),
            }
            for row in rows
        ]

    # --- user profile -----------------------------------------------------

    def set_fact(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO profile (key, value, ts) VALUES (?, ?, " + _NOW + ") "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, ts = " + _NOW,
            (key, value),
        )
        self.conn.commit()

    def get_fact(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM profile WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row is not None else None

    def all_facts(self) -> dict[str, str]:
        rows = self.conn.execute(
            "SELECT key, value FROM profile ORDER BY key"
        ).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def delete_fact(self, key: str) -> bool:
        cur = self.conn.execute("DELETE FROM profile WHERE key = ?", (key,))
        self.conn.commit()
        return cur.rowcount > 0


def _split_tags(raw: str) -> list[str]:
    return [t for t in raw.split(",") if t]
