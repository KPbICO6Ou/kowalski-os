"""Proactive heartbeat: every N minutes the agent wakes for a brief check-in.

The heartbeat runs the agent loop on a fixed check-in prompt and notifies the
user only when the agent reports it did something useful. A "nothing to do"
beat is silent.

Safety
------
A heartbeat run has NO human present to confirm anything, so any
destructive / confirm-requiring tool step fails closed: it is denied on the
confirmation timeout. That is intended. A heartbeat can therefore only
complete auto-allowed steps (reads and in-allowlist writes); anything that
needs interactive approval will be refused and the beat works around it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from .agent.events import DoneEvent
from .agent.loop import AgentLoop
from . import platform

log = logging.getLogger(__name__)

#: Sentinel the agent must reply with verbatim when no action is warranted.
NOTHING_TO_DO = "NOTHING_TO_DO"

DEFAULT_PROMPT = (
    "This is an automated proactive check-in; no human is available to confirm "
    "any action. Review the pending reminders and recent context and decide if "
    "anything useful should be done right now. If yes, do it using only safe, "
    "read-only or already-allowed actions, then summarise briefly what you did. "
    f"If nothing useful needs doing, reply with exactly {NOTHING_TO_DO} and nothing else."
)

LoopFactory = Callable[[], AgentLoop]
NotifyFn = Callable[[str, str], Awaitable[object]]


class HeartbeatService:
    """Periodically wake the agent for a brief, safe check-in.

    Each beat builds a fresh ``AgentLoop`` via ``loop_factory`` (the same
    pattern the daemon uses), so beats never share mutable loop state.
    """

    def __init__(
        self,
        loop_factory: LoopFactory,
        *,
        interval_min: int = 30,
        prompt: str = DEFAULT_PROMPT,
        notify: NotifyFn = platform.notify,
        scheduler=None,
    ):
        self._loop_factory = loop_factory
        self._interval_min = interval_min
        self._prompt = prompt
        self._notify = notify
        self._scheduler = scheduler
        self._job = None
        self._task: asyncio.Task | None = None

    async def beat(self) -> str | None:
        """Run one check-in. Notify and return the answer only if useful.

        Returns the answer text when the agent reports it did something, after
        sending a notification; returns ``None`` when there was nothing to do
        or when the run failed. Never raises.
        """
        try:
            loop = self._loop_factory()
            answer = ""
            async for event in loop.run(self._prompt):
                if isinstance(event, DoneEvent):
                    answer = event.answer
        except Exception:
            log.exception("heartbeat beat failed")
            return None

        answer = (answer or "").strip()
        if not answer or answer == NOTHING_TO_DO:
            return None

        try:
            await self._notify("Kowalski", answer)
        except Exception:
            log.exception("heartbeat notification failed")
            return None
        return answer

    def start(self) -> None:
        """Begin beating. Uses the given scheduler if any, else a background task."""
        if self._scheduler is not None:
            from apscheduler.triggers.interval import IntervalTrigger

            self._job = self._scheduler.add_job(
                self.beat,
                IntervalTrigger(minutes=self._interval_min),
                id="heartbeat",
                replace_existing=True,
            )
        elif self._task is None:
            self._task = asyncio.create_task(self._run_forever(), name="heartbeat")

    def stop(self) -> None:
        """Stop beating, removing the scheduler job or cancelling the task."""
        if self._job is not None and self._scheduler is not None:
            try:
                self._scheduler.remove_job("heartbeat")
            except Exception:
                pass
            self._job = None
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run_forever(self) -> None:
        while True:
            await asyncio.sleep(self._interval_min * 60)
            await self.beat()
