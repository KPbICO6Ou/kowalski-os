"""Default tool set assembly."""

from __future__ import annotations

from .config import Config
from .journal import ActionJournal
from .policy import ConfirmationProvider, SecurityPolicy
from .scheduler import ReminderScheduler
from .store import Store
from .tools import apps, files, notes, reminders, system
from .tools.registry import ToolRegistry


def build_default_registry(
    config: Config,
    store: Store,
    scheduler: ReminderScheduler,
    confirmer: ConfirmationProvider,
) -> ToolRegistry:
    policy = SecurityPolicy(
        allowed_paths=config.allowed_paths,
        auto_allow_network=config.get_bool("KOW_AUTO_ALLOW_NETWORK"),
    )
    registry = ToolRegistry(
        policy=policy,
        journal=ActionJournal(store),
        confirmer=confirmer,
        tool_timeout=float(config.get_int("KOW_TOOL_TIMEOUT")),
    )
    registry.register_all(system.TOOLS)
    registry.register_all(apps.TOOLS)
    registry.register_all(files.build_tools(config.allowed_paths))
    registry.register_all(notes.build_tools(store))
    registry.register_all(reminders.build_tools(scheduler))
    return registry
