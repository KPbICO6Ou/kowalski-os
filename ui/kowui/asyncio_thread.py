"""A background thread running an asyncio event loop, shared by the GTK windows
(omnibox, mail): GTK owns the process main loop, controllers live on this loop,
and widget updates are marshalled back with GLib.idle_add."""

from __future__ import annotations

import asyncio
import threading


class AsyncioThread:
    def __init__(self, name: str = "kowui-asyncio") -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.run_loop, name=name, daemon=True)

    def run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def start(self) -> None:
        self.thread.start()

    def submit(self, coro) -> None:
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
