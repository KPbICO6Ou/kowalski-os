"""End-to-end socket IPC test with a FakeLLM-backed AgentService."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from kowalski.agent.llm import ToolCall
from kowalski.agent.loop import AgentLoop
from kowalski.conversations import ConversationStore
from kowalski.ipc.base import AgentService, PendingQueueConfirmation
from kowalski.ipc.socket_service import SocketIpcServer
from kowalski.journal import ActionJournal
from kowalski.policy import SecurityPolicy
from kowalski.tools.base import RiskLevel, ToolDef, ToolResult
from kowalski.tools.registry import ToolRegistry

from .fake_llm import FakeLLM


class WriteArgs(BaseModel):
    path: str


async def write_handler(args) -> ToolResult:
    return ToolResult(ok=True, content="written")


@pytest.fixture
def short_sock_path():
    # AF_UNIX paths are limited to ~104 bytes on macOS; pytest tmp_path is too long
    import shutil
    import tempfile

    sock_dir = tempfile.mkdtemp(prefix="kow", dir="/tmp")
    yield Path(sock_dir) / "kow.sock"
    shutil.rmtree(sock_dir, ignore_errors=True)


@pytest.fixture
async def ipc(tmp_path: Path, tmp_store, short_sock_path):
    confirmations = PendingQueueConfirmation(timeout=5.0)
    registry = ToolRegistry(
        policy=SecurityPolicy(allowed_paths=[tmp_path / "allowed"]),
        journal=ActionJournal(tmp_store),
        confirmer=confirmations,
        tool_timeout=5.0,
    )
    registry.register(ToolDef(
        name="test.write", description="w", args_model=WriteArgs,
        risk=RiskLevel.WRITE, handler=write_handler, path_fields=("path",),
    ))
    # A home path is neither in the allowlist nor under a forbidden root -> CONFIRM.
    # (pytest tmp_path lives under /private/var on macOS, which is DENY territory.)
    confirm_path = str(Path.home() / "kow-test-never-written.txt")
    llm = FakeLLM([
        [ToolCall(name="test.write", args={"path": confirm_path})],
        "All done.",
    ])
    service = AgentService(lambda: AgentLoop(llm, registry), registry, confirmations)
    server = SocketIpcServer(short_sock_path, service)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.05)
    yield server
    task.cancel()
    await server.shutdown()


@pytest.fixture
async def conv_ipc(tmp_path: Path, tmp_store, short_sock_path):
    """Socket server with conversation persistence and a text-only FakeLLM."""
    confirmations = PendingQueueConfirmation(timeout=5.0)
    registry = ToolRegistry(
        policy=SecurityPolicy(allowed_paths=[tmp_path]),
        journal=ActionJournal(tmp_store),
        confirmer=confirmations,
        tool_timeout=5.0,
    )
    llm = FakeLLM(["Paris is the capital.", "About 2.1 million people."])
    service = AgentService(
        lambda: AgentLoop(llm, registry),
        registry,
        confirmations,
        conversations=ConversationStore(tmp_store),
    )
    server = SocketIpcServer(short_sock_path, service)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.05)
    yield server, llm
    task.cancel()
    await server.shutdown()


async def send_recv_lines(sock_path: Path, request: dict, n_responses: int | None = None):
    reader, writer = await asyncio.open_unix_connection(str(sock_path))
    writer.write((json.dumps(request) + "\n").encode())
    await writer.drain()
    lines = []
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=5)
        if not line:
            break
        payload = json.loads(line)
        lines.append(payload)
        if n_responses and len(lines) >= n_responses:
            break
        if payload.get("event") in ("DoneEvent", "ErrorEvent"):
            break
    writer.close()
    return lines


async def test_status_and_tools(ipc: SocketIpcServer):
    status = (await send_recv_lines(ipc.socket_path, {"op": "status"}, 1))[0]
    assert status["tools"] == 1
    tools = (await send_recv_lines(ipc.socket_path, {"op": "tools"}, 1))[0]
    assert tools["tools"][0]["name"] == "test.write"


async def test_ask_with_confirm_roundtrip(ipc: SocketIpcServer):
    """tmp file path is outside the allowlist -> CONFIRM flows through the stream;
    a second connection approves it; the loop completes."""
    reader, writer = await asyncio.open_unix_connection(str(ipc.socket_path))
    writer.write((json.dumps({"op": "ask", "prompt": "write the file"}) + "\n").encode())
    await writer.drain()

    events = []
    done = False
    while not done:
        line = await asyncio.wait_for(reader.readline(), timeout=5)
        payload = json.loads(line)
        events.append(payload)
        if payload.get("event") == "ConfirmRequestEvent":
            # approve from a separate connection (like a GUI would)
            response = await send_recv_lines(
                ipc.socket_path,
                {"op": "confirm", "request_id": payload["request_id"], "approved": True},
                1,
            )
            assert response[0]["ok"] is True
        if payload.get("event") in ("DoneEvent", "ErrorEvent"):
            done = True
    writer.close()

    kinds = [e.get("event") for e in events]
    assert "ConfirmRequestEvent" in kinds
    assert "ToolResultEvent" in kinds
    assert kinds[-1] == "DoneEvent"
    tool_result = next(e for e in events if e.get("event") == "ToolResultEvent")
    assert tool_result["ok"] is True


async def test_two_turn_conversation_over_socket(conv_ipc):
    """A second ask with the same conversation_id sees the first answer
    in the LLM messages; the conversations op lists the conversation."""
    server, llm = conv_ipc

    first = await send_recv_lines(
        server.socket_path,
        {"op": "ask", "prompt": "What is the capital of France?", "conversation_id": "conv-1"},
    )
    assert first[-1]["event"] == "DoneEvent"
    assert "Paris" in first[-1]["answer"]

    second = await send_recv_lines(
        server.socket_path,
        {"op": "ask", "prompt": "How many people live there?", "conversation_id": "conv-1"},
    )
    assert second[-1]["event"] == "DoneEvent"

    messages = llm.calls[1]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert "Paris is the capital." in messages[2]["content"]

    listing = (await send_recv_lines(server.socket_path, {"op": "conversations"}, 1))[0]
    assert len(listing["conversations"]) == 1
    conv = listing["conversations"][0]
    assert conv["id"] == "conv-1"
    assert conv["title"] == "What is the capital of France?"
    assert conv["messages"] == 4
