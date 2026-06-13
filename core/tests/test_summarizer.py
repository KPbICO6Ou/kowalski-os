"""Tests for conversation auto-summarisation (summarizer + run_turn path)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from kowalski.agent.llm import ChatChunk
from kowalski.agent.loop import AgentLoop
from kowalski.conversations import SUMMARY_PREFIX, ConversationStore, run_turn
from kowalski.store import Store
from kowalski.summarizer import summarize_messages
from kowalski.tools.registry import ToolRegistry

from .fake_llm import FakeLLM


class RaisingLLM:
    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[ChatChunk]:
        raise RuntimeError("boom")
        yield  # pragma: no cover - makes this an async generator


@pytest.fixture
def conversations(tmp_store: Store) -> ConversationStore:
    return ConversationStore(tmp_store)


async def test_summarize_messages_returns_scripted_summary():
    llm = FakeLLM(["Dense digest of facts."])
    out = await summarize_messages(
        llm, [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
    )
    assert out == "Dense digest of facts."


async def test_summarize_messages_empty_input_skips_call():
    llm = FakeLLM(["should not be used"])
    assert await summarize_messages(llm, []) == ""
    assert llm.calls == []


async def test_summarize_messages_returns_empty_on_error():
    out = await summarize_messages(RaisingLLM(), [{"role": "user", "content": "hi"}])
    assert out == ""


def test_summary_column_migration_is_idempotent(tmp_store: Store):
    # Constructing twice over the same connection must not raise.
    ConversationStore(tmp_store)
    store2 = ConversationStore(tmp_store)
    store2.touch("c1")
    store2.set_summary("c1", "remembered")
    assert store2.get_summary("c1") == "remembered"


async def test_long_conversation_summarises_old_turns(
    registry: ToolRegistry, conversations: ConversationStore
):
    # Script: the summariser call, then the next real turn's answer.
    llm = FakeLLM(["SUMMARY-OF-OLD-TURNS", "Latest reply."])
    loop = AgentLoop(llm, registry)

    # Seed a long conversation directly so we cross the threshold.
    conversations.touch("c1", title_hint="seed")
    for i in range(10):
        conversations.append("c1", "user", f"old user {i}")
        conversations.append("c1", "assistant", f"old assistant {i}")
    # 20 stored messages > summarize_after=6.

    async for _ in run_turn(loop, "new question", "c1", conversations, summarize_after=6, keep=4):
        pass

    # A summary was produced and stored.
    assert conversations.get_summary("c1") == "SUMMARY-OF-OLD-TURNS"

    # First LLM call is the summariser; second is the real turn.
    summariser_call = llm.calls[0]
    assert summariser_call[0]["role"] == "system"
    assert "old user 0" in summariser_call[1]["content"]

    turn_call = llm.calls[1]
    contents = "\n".join(m["content"] for m in turn_call)
    # The digest is present in the effective history...
    assert SUMMARY_PREFIX + "SUMMARY-OF-OLD-TURNS" in contents
    # ...and only the kept recent turns survive verbatim (not the oldest).
    assert "old user 0" not in contents
    assert "old assistant 9" in contents
    assert "new question" in contents


async def test_existing_summary_is_merged_on_next_summarisation(
    registry: ToolRegistry, conversations: ConversationStore
):
    llm = FakeLLM(["MERGED-SUMMARY", "reply"])
    loop = AgentLoop(llm, registry)

    conversations.touch("c1", title_hint="seed")
    conversations.set_summary("c1", "PRIOR-SUMMARY")
    for i in range(10):
        conversations.append("c1", "user", f"u{i}")
        conversations.append("c1", "assistant", f"a{i}")

    async for _ in run_turn(loop, "q", "c1", conversations, summarize_after=6, keep=4):
        pass

    # The prior summary fed into the summariser's excerpt.
    summariser_call = llm.calls[0]
    excerpt = summariser_call[1]["content"]
    assert "PRIOR-SUMMARY" in excerpt
    # The stored summary is replaced by the freshly merged one.
    assert conversations.get_summary("c1") == "MERGED-SUMMARY"


async def test_short_conversation_is_unaffected(
    registry: ToolRegistry, conversations: ConversationStore
):
    llm = FakeLLM(["First answer.", "Second answer."])
    loop = AgentLoop(llm, registry)

    async for _ in run_turn(loop, "first", "c1", conversations, summarize_after=24, keep=8):
        pass
    async for _ in run_turn(loop, "second", "c1", conversations, summarize_after=24, keep=8):
        pass

    # No summary stored for a short conversation.
    assert conversations.get_summary("c1") is None

    # Full history passed verbatim on the second turn, no synthetic summary msg.
    second_call = llm.calls[1]
    assert [m["role"] for m in second_call] == ["system", "user", "assistant", "user"]
    assert all(SUMMARY_PREFIX not in m["content"] for m in second_call)
    assert "First answer." in second_call[2]["content"]
    assert second_call[3]["content"] == "second"


async def test_summariser_failure_falls_back_to_plain_recent_history(
    registry: ToolRegistry, conversations: ConversationStore
):
    # Summariser raises -> no summary stored, but the turn still proceeds with
    # the recent (kept) turns only.
    class HalfRaising:
        def __init__(self):
            self.calls: list[list[dict[str, Any]]] = []
            self._n = 0

        async def chat(
            self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
        ) -> AsyncIterator[ChatChunk]:
            self.calls.append(list(messages))
            self._n += 1
            if self._n == 1:  # the summariser call
                raise RuntimeError("summary boom")
            yield ChatChunk(content_delta="ok", done=True)

    llm = HalfRaising()
    loop = AgentLoop(llm, registry)
    conversations.touch("c1", title_hint="seed")
    for i in range(10):
        conversations.append("c1", "user", f"u{i}")
        conversations.append("c1", "assistant", f"a{i}")

    async for _ in run_turn(loop, "q", "c1", conversations, summarize_after=6, keep=4):
        pass

    assert conversations.get_summary("c1") is None
    turn_call = llm.calls[1]
    contents = "\n".join(m["content"] for m in turn_call)
    assert SUMMARY_PREFIX not in contents
    assert "u0" not in contents  # old turns dropped, no digest to carry them
