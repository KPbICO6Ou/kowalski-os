"""Async client for the kow-core unix-socket IPC, used by the omnibox.

This is a thin adapter over the canonical ``kowalski.ipc.client.AgentClient``;
the protocol itself lives in core. ``DaemonUnavailableError`` is re-exported here
so existing ``from kowui.client import DaemonUnavailableError`` imports keep
working.
"""

from __future__ import annotations

from pathlib import Path

from kowalski.config import Config
from kowalski.ipc.client import AgentClient, DaemonUnavailableError

__all__ = ["DaemonUnavailableError", "OmniClient", "default_socket_path"]


def default_socket_path() -> Path:
    """Resolve the daemon socket path the same way kow-core does."""
    return Config.load().socket_path


class OmniClient(AgentClient):
    """Omnibox client over the kow-core socket IPC.

    Keeps the public surface ``kowui.controller`` and the UI tests rely on
    (``ask``/``confirm``/``status``/``tools`` and async-context-manager use)
    while delegating the wire protocol to ``AgentClient``.

    Usage::

        async with OmniClient() as client:
            async for event in client.ask("hello", conversation_id):
                ...
    """

    def __init__(self, socket_path: Path | str | None = None):
        super().__init__(socket_path)

    async def __aenter__(self) -> "OmniClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def tools(self) -> dict:  # type: ignore[override]
        """Return the raw ``{"tools": [...]}`` reply (omnibox-facing shape)."""
        return await self._request({"op": "tools"})
