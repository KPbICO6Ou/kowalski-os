"""ConversationStore unit tests + a two-turn AgentService flow over FakeLLM."""

import pytest

from kowalski.agent.loop import AgentLoop
from kowalski.conversations import ConversationStore
from kowalski.ipc.base import AgentService, PendingQueueConfirmation
from kowalski.tools.registry import ToolRegistry

from .fake_llm import FakeLLM


@pytest.fixture
def conversations(tmp_store) -> ConversationStore:
    return ConversationStore(tmp_store)


def test_touch_creates_and_sets_title_from_first_prompt(conversations: ConversationStore):
    conversations.touch("c1", title_hint="What is the capital of France?\nsecond line")
    conversations.touch("c1", title_hint="a different later prompt")
    recent = conversations.list_recent()
    assert len(recent) == 1
    assert recent[0]["id"] == "c1"
    assert recent[0]["title"] == "What is the capital of France?"


def test_touch_truncates_long_titles(conversations: ConversationStore):
    conversations.touch("c1", title_hint="x" * 200)
    assert len(conversations.list_recent()[0]["title"]) == 60


def test_append_and_history_roundtrip(conversations: ConversationStore):
    conversations.touch("c1")
    conversations.append("c1", "user", "hi")
    conversations.append("c1", "assistant", "hello")
    assert conversations.history("c1") == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    assert conversations.history("other") == []


def test_history_caps_at_max_messages_keeping_newest(conversations: ConversationStore):
    conversations.touch("c1")
    for i in range(30):
        conversations.append("c1", "user", f"msg {i}")
    history = conversations.history("c1", max_messages=20)
    assert len(history) == 20
    assert history[0]["content"] == "msg 10"  # oldest-first, last 20 kept
    assert history[-1]["content"] == "msg 29"


def test_last_conversation_id_tracks_activity(conversations: ConversationStore):
    assert conversations.last_conversation_id() is None
    conversations.touch("c1")
    conversations.touch("c2")
    conversations.append("c1", "user", "bump")  # c1 becomes most recently updated
    assert conversations.last_conversation_id() == "c1"


def test_list_recent_limit_and_counts(conversations: ConversationStore):
    for i in range(12):
        conversations.touch(f"c{i}", title_hint=f"prompt {i}")
    conversations.append("c3", "user", "hi")
    conversations.append("c3", "assistant", "hello")
    recent = conversations.list_recent(limit=10)
    assert len(recent) == 10
    assert recent[0]["id"] == "c3"  # most recently updated first
    assert recent[0]["messages"] == 2


async def test_two_turn_ask_feeds_first_answer_back_to_llm(
    registry: ToolRegistry, conversations: ConversationStore
):
    llm = FakeLLM(["Paris is the capital.", "About 2.1 million people."])
    service = AgentService(
        lambda: AgentLoop(llm, registry),
        registry,
        PendingQueueConfirmation(timeout=1.0),
        conversations=conversations,
    )

    async for _ in service.ask("What is the capital of France?", conversation_id="c1"):
        pass
    async for _ in service.ask("How many people live there?", conversation_id="c1"):
        pass

    second_call = llm.calls[1]
    roles = [m["role"] for m in second_call]
    assert roles == ["system", "user", "assistant", "user"]
    assert "Paris is the capital." in second_call[2]["content"]
    assert second_call[1]["content"] == "What is the capital of France?"
    assert second_call[3]["content"] == "How many people live there?"

    history = conversations.history("c1")
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]


async def test_ask_without_conversations_does_not_persist(registry: ToolRegistry, tmp_store):
    llm = FakeLLM(["Hello there."])
    service = AgentService(
        lambda: AgentLoop(llm, registry), registry, PendingQueueConfirmation(timeout=1.0)
    )
    async for _ in service.ask("hi", conversation_id="c1"):
        pass
    assert service.list_conversations() == []
    assert ConversationStore(tmp_store).history("c1") == []
