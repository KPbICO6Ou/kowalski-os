"""IPC server factory: D-Bus on Linux when available, unix socket otherwise."""

from __future__ import annotations

import sys

from ..config import Config
from .base import IpcServer


def make_ipc_server(config: Config, agent_service) -> IpcServer:
    backend = config.get("KOW_IPC", "")
    if backend == "socket" or not sys.platform.startswith("linux"):
        from .socket_service import SocketIpcServer

        return SocketIpcServer(config.socket_path, agent_service)
    try:
        from .dbus_service import DbusIpcServer

        return DbusIpcServer(agent_service)
    except ImportError:
        from .socket_service import SocketIpcServer

        return SocketIpcServer(config.socket_path, agent_service)
