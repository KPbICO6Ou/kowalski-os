"""Live-Ollama integration tests. Enable with KOW_TEST_OLLAMA=1
(optionally KOW_TEST_MODEL=qwen2.5:14b)."""

import os

import pytest

from kowalski.agent.events import DoneEvent, ToolCallEvent
from kowalski.agent.llm import OllamaLLM
from kowalski.agent.loop import AgentLoop
from kowalski.tools import system

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("KOW_TEST_OLLAMA") != "1",
        reason="set KOW_TEST_OLLAMA=1 to run against a live Ollama",
    ),
]


@pytest.fixture
def llm():
    return OllamaLLM(
        host=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
        model=os.environ.get("KOW_TEST_MODEL", "qwen2.5:14b"),
    )


async def test_disk_question_calls_system_info(registry, llm):
    registry.register_all(system.TOOLS)
    loop = AgentLoop(llm, registry, max_iterations=4)
    events = [event async for event in loop.run("How much free disk space do I have? Answer briefly.")]
    tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert any(e.tool == "system.info" for e in tool_calls)
    done = [e for e in events if isinstance(e, DoneEvent)]
    assert done and done[0].answer.strip()
