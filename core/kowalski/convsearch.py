"""Read-only substring search over stored conversation messages.

Plain ``LIKE`` over the ``messages`` table joined to ``conversations`` for the
title. No schema changes are made here.

Future upgrade: a SQLite FTS5 virtual table (contentless, mirroring
``messages.content``) would give ranked, tokenized full-text search and phrase
queries instead of the current substring scan; it is deferred to keep this tool
strictly read-only with no migration.
"""

from __future__ import annotations

from typing import Any

from .store import Store

SNIPPET_MAX_CHARS = 200


def _snippet(content: str, limit: int = SNIPPET_MAX_CHARS) -> str:
    """Trim a message to a single-line snippet of at most ``limit`` chars."""
    flattened = " ".join(content.split())
    if len(flattened) <= limit:
        return flattened
    return flattened[: limit - 1].rstrip() + "…"


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so user input is matched literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ConversationSearch:
    """Substring search over past chat messages."""

    def __init__(self, store: Store):
        self.conn = store.conn

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Find messages whose content contains ``query`` (case-insensitive).

        Newest-first. Each result is
        ``{conversation_id, title, role, ts, snippet}``.
        """
        pattern = f"%{_escape_like(query)}%"
        rows = self.conn.execute(
            """
            SELECT m.conversation_id AS conversation_id,
                   c.title AS title,
                   m.role AS role,
                   m.ts AS ts,
                   m.content AS content
            FROM messages m
            LEFT JOIN conversations c ON c.id = m.conversation_id
            WHERE m.content LIKE ? ESCAPE '\\'
            ORDER BY m.ts DESC, m.id DESC
            LIMIT ?
            """,
            (pattern, limit),
        ).fetchall()
        return [
            {
                "conversation_id": r["conversation_id"],
                "title": r["title"],
                "role": r["role"],
                "ts": r["ts"],
                "snippet": _snippet(r["content"]),
            }
            for r in rows
        ]
