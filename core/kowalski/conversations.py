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
from .summarizer import summarize_messages

TITLE_MAX_CHARS = 60

# Defaults used when the integrator has not wired config keys yet. Once a
# conversation holds more than `SUMMARIZE_AFTER` stored messages, the turns
# older than the most recent `KEEP_RECENT` are folded into a summary.
SUMMARIZE_AFTER = 24
KEEP_RECENT = 8

# Synthetic message carrying the rolling digest of older turns. Stored as a
# `user` role because the messages CHECK constraint only allows user/assistant.
SUMMARY_PREFIX = "[Earlier conversation summary]\n"


class ConversationStore:
    """CRUD over the conversations/messages tables."""

    def __init__(self, store: Store):
        self.conn = store.conn
        self._ensure_summary_column()

    def _ensure_summary_column(self) -> None:
        """Idempotent migration: add the `summary` column if it is missing."""
        try:
            self.conn.execute("ALTER TABLE conversations ADD COLUMN summary TEXT")
            self.conn.commit()
        except Exception:
            # Column already exists (or the table is being shared concurrently);
            # the ALTER is the migration and re-running it is a no-op for us.
            pass

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

    def message_count(self, conversation_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        return int(row["n"]) if row else 0

    def get_summary(self, conversation_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT summary FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        return row["summary"] if row and row["summary"] else None

    def set_summary(self, conversation_id: str, text: str) -> None:
        self.conn.execute(
            "UPDATE conversations SET summary = ? WHERE id = ?",
            (text, conversation_id),
        )
        self.conn.commit()

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


async def _effective_history(
    agent_loop: AgentLoop,
    conversations: ConversationStore,
    conversation_id: str,
    summarize_after: int,
    keep: int,
) -> list[dict[str, Any]]:
    """History with older turns folded into a rolling summary.

    When the stored message count exceeds `summarize_after`, the turns older
    than the most recent `keep` are summarised (merged with any prior summary)
    and persisted, so the next turn starts from the digest. The returned list
    is the synthetic summary message (if any) followed by the kept turns."""
    count = conversations.message_count(conversation_id)
    summary = conversations.get_summary(conversation_id)

    if count > summarize_after:
        # Pull everything, split off the turns to compress from the kept tail.
        full = conversations.history(conversation_id, max_messages=count)
        older = full[:-keep] if keep > 0 else full
        if older:
            excerpt = older
            if summary:
                excerpt = [
                    {"role": "user", "content": SUMMARY_PREFIX + summary},
                    *older,
                ]
            new_summary = await summarize_messages(agent_loop.llm, excerpt)
            if new_summary:
                summary = new_summary
                conversations.set_summary(conversation_id, summary)

    recent = conversations.history(conversation_id, max_messages=keep)
    effective: list[dict[str, Any]] = []
    if summary:
        effective.append({"role": "user", "content": SUMMARY_PREFIX + summary})
    effective.extend(recent)
    return effective


async def run_turn(
    agent_loop: AgentLoop,
    prompt: str,
    conversation_id: str,
    conversations: ConversationStore | None,
    *,
    summarize_after: int = SUMMARIZE_AFTER,
    keep: int = KEEP_RECENT,
) -> AsyncIterator[AgentEvent]:
    """Run one agent turn, loading prior history and persisting the new turns.

    The user prompt is persisted up front; the assistant turn only when the
    stream ends with a DoneEvent (errors keep just the user turn).

    Long conversations are auto-summarised: turns older than `keep` are folded
    into a rolling digest once the stored message count exceeds
    `summarize_after`. Both thresholds default to safe values and can be
    overridden by the integrator (KOW_SUMMARIZE_AFTER / KOW_SUMMARIZE_KEEP)."""
    history = None
    if conversations is not None:
        conversations.touch(conversation_id, title_hint=prompt)
        history = await _effective_history(
            agent_loop, conversations, conversation_id, summarize_after, keep
        )
        conversations.append(conversation_id, "user", prompt)

    answer: str | None = None
    async for event in agent_loop.run(prompt, history=history, conversation_id=conversation_id):
        if isinstance(event, DoneEvent):
            answer = event.answer
        yield event

    if conversations is not None and answer is not None:
        conversations.append(conversation_id, "assistant", answer)
