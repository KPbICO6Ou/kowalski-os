"""Recipe engine: run step chains through the ToolRegistry and arm triggers.

Every step is dispatched via ``ToolRegistry.execute``, so the security policy,
confirmation prompt and action journal apply to each call exactly as for a
direct tool invocation. A recipe containing a destructive (or out-of-allowlist
write / network) step therefore prompts for confirmation AT RUN TIME, when the
step executes — recipes do not bypass any safeguard.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .model import Recipe, Step
from .store import RecipeStore

if TYPE_CHECKING:
    from ..tools.registry import ToolRegistry

log = logging.getLogger(__name__)

# {{ steps.<index>.<field> }} — index is zero-based over already-run steps.
_TEMPLATE = re.compile(r"\{\{\s*steps\.(\d+)\.([A-Za-z0-9_]+)\s*\}\}")


class RecipeEngine:
    def __init__(
        self,
        store: RecipeStore,
        registry: ToolRegistry,
        scheduler: AsyncIOScheduler | None = None,
    ):
        self._store = store
        self._registry = registry
        self._scheduler = scheduler
        self._watchers: dict[str, Any] = {}

    async def run(self, name: str, conversation_id: str | None = None) -> list[dict[str, Any]]:
        """Run the named recipe's steps in order, threading each step's result
        data into later steps' ``{{ steps.N.field }}`` templates.

        Returns one ``{step, tool, ok, content}`` dict per executed step. Stops
        at the first step that returns ``ok=False`` (failed / denied by policy /
        denied by user) and the summary records where it stopped.
        """
        recipe = self._store.get(name)
        if recipe is None:
            raise ValueError(f"no recipe named {name!r}")

        results: list[dict[str, Any]] = []
        step_data: list[Any] = []
        for index, step in enumerate(recipe.steps):
            resolved = self._resolve_args(step, step_data)
            result = await self._registry.execute(step.tool, resolved, conversation_id)
            results.append(
                {"step": index, "tool": step.tool, "ok": result.ok, "content": result.content}
            )
            step_data.append(result.data)
            if not result.ok:
                results[-1]["stopped"] = True
                log.info("recipe %s stopped at step %d (%s)", name, index, step.tool)
                break
        return results

    def _resolve_args(self, step: Step, step_data: list[Any]) -> dict[str, Any]:
        return {key: self._resolve_value(value, step_data) for key, value in step.args.items()}

    def _resolve_value(self, value: Any, step_data: list[Any]) -> Any:
        if not isinstance(value, str):
            return value

        def replace(match: re.Match[str]) -> str:
            idx = int(match.group(1))
            key = match.group(2)
            if idx >= len(step_data):
                raise ValueError(f"template references step {idx} which has not run yet")
            data = step_data[idx]
            if isinstance(data, dict) and key in data:
                return str(data[key])
            raise ValueError(f"step {idx} result has no field {key!r}")

        return _TEMPLATE.sub(replace, value)

    # -- trigger arming -----------------------------------------------------

    def arm_all(self) -> None:
        """(Re-)register triggers for every saved recipe."""
        for recipe in self._store.list():
            self.arm(recipe)

    def arm(self, recipe: Recipe) -> None:
        """Register this recipe's trigger on the scheduler.

        ``manual`` does nothing (run explicitly); ``time``/``interval`` use
        APScheduler's DateTrigger/IntervalTrigger; ``inotify`` lazily uses
        ``watchdog`` and is skipped with a warning if it is not installed.
        """
        if self._scheduler is None:
            log.debug("no scheduler; cannot arm recipe %s", recipe.name)
            return

        kind = recipe.trigger.kind
        if kind == "manual":
            return
        if kind == "time":
            self._scheduler.add_job(
                self._fire,
                DateTrigger(run_date=recipe.trigger.at),
                args=[recipe.name],
                id=self._job_id(recipe.name),
                replace_existing=True,
            )
        elif kind == "interval":
            self._scheduler.add_job(
                self._fire,
                IntervalTrigger(seconds=recipe.trigger.every_seconds),
                args=[recipe.name],
                id=self._job_id(recipe.name),
                replace_existing=True,
            )
        elif kind == "inotify":
            self._arm_inotify(recipe)

    def disarm(self, name: str) -> None:
        if self._scheduler is None:
            return
        try:
            self._scheduler.remove_job(self._job_id(name))
        except JobLookupError:
            pass
        watcher = self._watchers.pop(name, None)
        if watcher is not None:
            watcher.stop()

    def _arm_inotify(self, recipe: Recipe) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            log.warning(
                "watchdog not installed; skipping inotify trigger for recipe %s", recipe.name
            )
            return

        import asyncio

        loop = asyncio.get_event_loop()
        name = recipe.name
        engine = self

        class _Handler(FileSystemEventHandler):
            def on_any_event(self, event: object) -> None:
                asyncio.run_coroutine_threadsafe(engine._fire(name), loop)

        self.disarm(name)
        observer = Observer()
        observer.schedule(_Handler(), recipe.trigger.path, recursive=True)
        observer.start()
        self._watchers[name] = observer

    async def _fire(self, name: str) -> None:
        try:
            await self.run(name)
        except Exception:
            log.exception("recipe %s failed", name)

    @staticmethod
    def _job_id(name: str) -> str:
        return f"recipe-{name}"
