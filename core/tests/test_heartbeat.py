from collections.abc import AsyncIterator
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from kowalski.agent.llm import ChatChunk
from kowalski.agent.loop import AgentLoop
from kowalski.heartbeat import NOTHING_TO_DO, HeartbeatService

from .fake_llm import FakeLLM


class RecordingNotify:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, title: str, body: str) -> bool:
        self.calls.append((title, body))
        return True


class RaisingLLM:
    """An LLM whose chat() raises — the loop turns this into an ErrorEvent."""

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[ChatChunk]:
        raise RuntimeError("boom")
        yield  # pragma: no cover - makes this an async generator


def make_service(registry, llm, notify) -> HeartbeatService:
    return HeartbeatService(lambda: AgentLoop(llm, registry), notify=notify)


async def test_nothing_to_do_is_silent(registry):
    notify = RecordingNotify()
    service = make_service(registry, FakeLLM([NOTHING_TO_DO]), notify)
    result = await service.beat()
    assert result is None
    assert notify.calls == []


async def test_useful_answer_notifies(registry):
    notify = RecordingNotify()
    answer = "I re-armed your 9am reminder."
    service = make_service(registry, FakeLLM([answer]), notify)
    result = await service.beat()
    assert result == answer
    assert notify.calls == [("Kowalski", answer)]


async def test_empty_answer_is_silent(registry):
    notify = RecordingNotify()
    service = make_service(registry, FakeLLM(["   "]), notify)
    result = await service.beat()
    assert result is None
    assert notify.calls == []


async def test_beat_never_raises_on_llm_error(registry):
    notify = RecordingNotify()
    service = make_service(registry, RaisingLLM(), notify)
    result = await service.beat()
    assert result is None
    assert notify.calls == []


async def test_beat_never_raises_on_factory_error():
    notify = RecordingNotify()

    def bad_factory() -> AgentLoop:
        raise RuntimeError("no loop")

    service = HeartbeatService(bad_factory, notify=notify)
    result = await service.beat()
    assert result is None
    assert notify.calls == []


async def test_start_registers_job_and_stop_removes_it(registry):
    scheduler = AsyncIOScheduler()
    service = HeartbeatService(
        lambda: AgentLoop(FakeLLM([NOTHING_TO_DO]), registry),
        interval_min=15,
        scheduler=scheduler,
    )
    service.start()
    assert scheduler.get_job("heartbeat") is not None
    service.stop()
    assert scheduler.get_job("heartbeat") is None
