"""Local draft storage over the core SQLite Store. Drafts are an entirely local
concept (composed by the agent, reviewed by the user) and never live on the mail
backend until mail.send pushes one out."""

from __future__ import annotations

from ..store import Store
from .types import Draft

_SEP = "\n"


def _join(values: list[str]) -> str:
    return _SEP.join(values)


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [v for v in value.split(_SEP) if v]


class DraftStore:
    def __init__(self, store: Store):
        self._store = store

    def save(self, draft: Draft) -> int:
        cur = self._store.conn.execute(
            'INSERT INTO drafts ("to", cc, subject, body, in_reply_to)'
            " VALUES (?, ?, ?, ?, ?)",
            (
                _join(draft.to),
                _join(draft.cc),
                draft.subject,
                draft.body,
                draft.in_reply_to,
            ),
        )
        self._store.conn.commit()
        return int(cur.lastrowid or 0)

    def get(self, draft_id: int) -> Draft | None:
        row = self._store.conn.execute(
            "SELECT * FROM drafts WHERE id = ?", (draft_id,)
        ).fetchone()
        if row is None:
            return None
        return Draft(
            to=_split(row["to"]),
            subject=row["subject"],
            body=row["body"],
            cc=_split(row["cc"]),
            in_reply_to=row["in_reply_to"],
        )

    def mark_sent(self, draft_id: int) -> None:
        self._store.conn.execute(
            "UPDATE drafts SET sent = 1 WHERE id = ?", (draft_id,)
        )
        self._store.conn.commit()

    def list_drafts(self, include_sent: bool = False) -> list[dict]:
        sql = "SELECT * FROM drafts"
        if not include_sent:
            sql += " WHERE sent = 0"
        sql += " ORDER BY id DESC"
        rows = self._store.conn.execute(sql).fetchall()
        return [dict(row) for row in rows]
