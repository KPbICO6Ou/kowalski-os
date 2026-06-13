"""kow serve: composition root for the daemon."""

from __future__ import annotations

import asyncio
import logging
import signal

from .agent.loop import AgentLoop
from .bootstrap import build_default_registry, build_llm
from .config import Config
from .conversations import ConversationStore
from .ipc import make_ipc_server
from .ipc.base import AgentService, PendingQueueConfirmation
from .scheduler import ReminderScheduler
from .store import Store

log = logging.getLogger(__name__)


async def run_daemon(api: bool = False) -> int:
    config = Config.load()
    logging.basicConfig(level=config.get("KOW_LOG_LEVEL", "INFO"))

    store = Store(config.get_path("KOW_DB_PATH"))
    scheduler = ReminderScheduler(store)
    confirmations = PendingQueueConfirmation(
        timeout=float(config.get_int("KOW_CONFIRM_TIMEOUT"))
    )
    registry = build_default_registry(config, store, scheduler, confirmations)

    llm = build_llm(config)

    def loop_factory() -> AgentLoop:
        return AgentLoop(llm, registry, max_iterations=config.get_int("KOW_MAX_ITERATIONS"))

    conversations = ConversationStore(store)
    service = AgentService(loop_factory, registry, confirmations, conversations=conversations)
    ipc_server = make_ipc_server(config, service)

    scheduler.start()
    recipe_engine = getattr(registry, "recipe_engine", None)
    if recipe_engine is not None:
        recipe_engine.arm_all()  # re-arm saved time/interval/inotify recipes
    tasks = [asyncio.create_task(ipc_server.serve(), name="ipc")]

    if api or config.get_bool("KOW_API_ENABLED"):
        from .api import serve_api

        tasks.append(
            asyncio.create_task(
                serve_api(service, port=config.get_int("KOW_API_PORT")), name="api"
            )
        )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    log.info("kow-core daemon started")
    await stop.wait()
    log.info("shutting down")

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await ipc_server.shutdown()
    scheduler.shutdown()
    store.close()
    return 0
