"""Conversation persistence: final user/assistant turns only.

Tool-call intermediates are intentionally not stored — they can be huge and
the final answer summarizes them. `run_turn` is the shared load/persist logic
used by both the daemon-side AgentService and the in-process CLI path."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from .agent.events import AgentEvent, DoneEvent
from .agent.loop import AgentLoop
from .store import Store

TITLE_MAX_CHARS = 60


class ConversationStore:
    """CRUD over the conversations/messages tables."""

    def __init__(self, store: Store):
        self.conn = store.conn

    def touch(self, conversation_id: str, title_hint: str | None = None) -> None:
        """Upsert a conversation; the title comes from the first prompt."""
        title = None
        if title_hint:
            title = title_hint.strip().splitlines()[0][:TITLE_MAX_CHARS] or None
        self.conn.execute(
            """
            INSERT INTO conversations (id, title, activity)
            VALUES (?, ?, (SELECT COALESCE(MAX(activity), 0) + 1 FROM conversations))
            ON CONFLICT(id) DO UPDATE SET
                updated_ts = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                activity = (SELECT COALESCE(MAX(activity), 0) + 1 FROM conversations),
                title = COALESCE(conversations.title, excluded.title)
            """,
            (conversation_id, title),
        )
        self.conn.commit()

    def append(self, conversation_id: str, role: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (conversation_id, role, content),
        )
        self.conn.execute(
            "UPDATE conversations SET"
            " updated_ts = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),"
            " activity = (SELECT COALESCE(MAX(activity), 0) + 1 FROM conversations)"
            " WHERE id = ?",
            (conversation_id,),
        )
        self.conn.commit()

    def history(self, conversation_id: str, max_messages: int = 20) -> list[dict[str, Any]]:
        """Last `max_messages` turns, oldest-first, as chat-style dicts."""
        rows = self.conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ?"
            " ORDER BY id DESC LIMIT ?",
            (conversation_id, max_messages),
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def last_conversation_id(self) -> str | None:
        row = self.conn.execute(
            "SELECT id FROM conversations ORDER BY activity DESC LIMIT 1"
        ).fetchone()
        return row["id"] if row else None

    def list_recent(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT c.id, c.title, c.created_ts, c.updated_ts,
                   (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS messages
            FROM conversations c
            ORDER BY c.activity DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


async def run_turn(
    agent_loop: AgentLoop,
    prompt: str,
    conversation_id: str,
    conversations: ConversationStore | None,
) -> AsyncIterator[AgentEvent]:
    """Run one agent turn, loading prior history and persisting the new turns.

    The user prompt is persisted up front; the assistant turn only when the
    stream ends with a DoneEvent (errors keep just the user turn)."""
    history = None
    if conversations is not None:
        conversations.touch(conversation_id, title_hint=prompt)
        history = conversations.history(conversation_id)
        conversations.append(conversation_id, "user", prompt)

    answer: str | None = None
    async for event in agent_loop.run(prompt, history=history, conversation_id=conversation_id):
        if isinstance(event, DoneEvent):
            answer = event.answer
        yield event

    if conversations is not None and answer is not None:
        conversations.append(conversation_id, "assistant", answer)
