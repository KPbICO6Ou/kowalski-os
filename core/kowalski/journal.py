"""Action journal: every tool invocation is recorded, including denied ones."""

from __future__ import annotations

import json
from typing import Any

from .store import Store

EXCERPT_LIMIT = 500


class ActionJournal:
    def __init__(self, store: Store):
        self._store = store

    def record(
        self,
        *,
        tool: str,
        args: dict[str, Any],
        risk: str,
        decision: str,
        conversation_id: str | None = None,
        result_ok: bool | None = None,
        result_excerpt: str | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> int:
        if result_excerpt and len(result_excerpt) > EXCERPT_LIMIT:
            result_excerpt = result_excerpt[:EXCERPT_LIMIT] + "…"
        cur = self._store.conn.execute(
            "INSERT INTO journal (conversation_id, tool, args_json, risk, decision,"
            " result_ok, result_excerpt, duration_ms, error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                tool,
                json.dumps(args, ensure_ascii=False, default=str),
                risk,
                decision,
                None if result_ok is None else int(result_ok),
                result_excerpt,
                duration_ms,
                error,
            ),
        )
        self._store.conn.commit()
        return int(cur.lastrowid or 0)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._store.conn.execute(
            "SELECT * FROM journal ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
