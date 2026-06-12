"""OmniController: callback dispatch order and the confirm roundtrip."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from kowui.client import OmniClient
from kowui.controller import OmniController

from .conftest import CONFIRM_SCRIPT


class RecordingCallbacks:
    """Records every callback; optionally auto-answers confirm requests."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.controller: OmniController | None = None
        self.approve: bool = True

    def on_token(self, text: str) -> None:
        self.calls.append(("token", text))

    def on_tool(self, tool: str, args: dict[str, Any]) -> None:
        self.calls.append(("tool", tool, args))

    def on_tool_result(self, tool: str, ok: bool, content: str) -> None:
        self.calls.append(("tool_result", tool, ok, content))

    def on_confirm_request(
        self, request_id: str, tool: str, args: dict[str, Any], risk: str, reason: str
    ) -> None:
        self.calls.append(("confirm_request", request_id, tool, risk, reason))
        if self.controller is not None:
            asyncio.get_running_loop().create_task(
                self.controller.answer_confirm(request_id, self.approve)
            )

    def on_done(self, answer: str) -> None:
        self.calls.append(("done", answer))

    def on_error(self, message: str) -> None:
        self.calls.append(("error", message))


async def test_submit_streams_tokens_then_done(fake_daemon):
    callbacks = RecordingCallbacks()
    controller = OmniController(OmniClient(fake_daemon.socket_path), callbacks)
    await controller.submit("hi")
    assert callbacks.calls == [
        ("token", "Hello"),
        ("token", ", world"),
        ("done", "Hello, world"),
    ]


@pytest.mark.parametrize("fake_daemon", [CONFIRM_SCRIPT], indirect=True)
async def test_confirm_roundtrip_approve(fake_daemon):
    callbacks = RecordingCallbacks()
    controller = OmniController(OmniClient(fake_daemon.socket_path), callbacks)
    callbacks.controller = controller
    await controller.submit("write it")
    kinds = [c[0] for c in callbacks.calls]
    assert kinds == ["token", "tool", "confirm_request", "tool_result", "done"]
    # the fake server recorded the approval sent on a separate connection
    assert fake_daemon.confirms == [("req-1", True)]
    confirm_call = callbacks.calls[2]
    assert confirm_call[1:] == ("req-1", "fs.write", "write", "writes outside the allowlist")


async def test_conversation_id_is_stable_across_submits(fake_daemon):
    callbacks = RecordingCallbacks()
    controller = OmniController(OmniClient(fake_daemon.socket_path), callbacks)
    await controller.submit("first")
    await controller.submit("second")
    conv_ids = {ask["conversation_id"] for ask in fake_daemon.asks}
    assert conv_ids == {controller.conversation_id}
    assert len(controller.conversation_id) == 32  # uuid4 hex


async def test_transport_failure_surfaces_as_on_error(short_sock_path):
    callbacks = RecordingCallbacks()
    controller = OmniController(OmniClient(short_sock_path), callbacks)
    await controller.submit("hi")  # no daemon listening
    assert len(callbacks.calls) == 1
    kind, message = callbacks.calls[0]
    assert kind == "error"
    assert "kow serve" in message
