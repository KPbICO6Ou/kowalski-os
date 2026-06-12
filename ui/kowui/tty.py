"""Terminal REPL for the omnibox (`kow-omni --cli`).

Works anywhere Python runs (including macOS dev machines without GTK): streams
tokens as they arrive, shows dim tool lines, and prompts inline for
confirmation requests.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from typing import Any

from .client import OmniClient
from .controller import OmniController

DIM = "\033[2m"
RED = "\033[31m"
RESET = "\033[0m"


def format_tool_line(tool: str, args: dict[str, Any]) -> str:
    """Render a compact `tool(key=value, ...)` line for tool calls."""
    rendered = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return f"→ {tool}({rendered})"


def format_confirm_prompt(tool: str, risk: str, reason: str) -> str:
    """Render the confirmation question shown before `allow? [y/N]`."""
    return f"confirm {tool} [{risk}]: {reason}"


class TtyCallbacks:
    """Controller callbacks that write straight to stdout."""

    def __init__(self) -> None:
        self.confirm_queue: asyncio.Queue[tuple[str, str, str, str]] = asyncio.Queue()
        self.finished = asyncio.Event()
        self._streamed = False

    def on_token(self, text: str) -> None:
        self._streamed = True
        sys.stdout.write(text)
        sys.stdout.flush()

    def on_tool(self, tool: str, args: dict[str, Any]) -> None:
        self._newline_if_streaming()
        print(f"{DIM}{format_tool_line(tool, args)}{RESET}")

    def on_tool_result(self, tool: str, ok: bool, content: str) -> None:
        self._newline_if_streaming()
        status = "ok" if ok else "failed"
        first_line = content.splitlines()[0] if content else ""
        print(f"{DIM}← {tool}: {status} {first_line}{RESET}")

    def on_confirm_request(
        self, request_id: str, tool: str, args: dict[str, Any], risk: str, reason: str
    ) -> None:
        self._newline_if_streaming()
        # the REPL loop picks this up and asks the user
        self.confirm_queue.put_nowait((request_id, tool, risk, reason))

    def on_done(self, answer: str) -> None:
        if not self._streamed and answer:
            print(answer, end="")
        print()
        self.finished.set()

    def on_error(self, message: str) -> None:
        self._newline_if_streaming()
        print(f"{RED}error: {message}{RESET}", file=sys.stderr)
        self.finished.set()

    def _newline_if_streaming(self) -> None:
        if self._streamed:
            print()
            self._streamed = False

    def reset(self) -> None:
        self.finished.clear()
        self._streamed = False


def _read_line(prompt: str) -> str | None:
    """Blocking input(); returns None on EOF (Ctrl-D)."""
    try:
        return input(prompt)
    except EOFError:
        return None


async def _ask_confirm(
    controller: OmniController, request_id: str, tool: str, risk: str, reason: str
) -> None:
    question = f"{format_confirm_prompt(tool, risk, reason)}\nallow? [y/N] "
    answer = await asyncio.to_thread(_read_line, question)
    approved = (answer or "").strip().lower() in ("y", "yes")
    await controller.answer_confirm(request_id, approved)
    print(f"{DIM}{'approved' if approved else 'denied'}{RESET}")


async def _run_one(controller: OmniController, callbacks: TtyCallbacks, prompt: str) -> None:
    """Drive one ask, answering confirm requests from stdin as they arrive."""
    callbacks.reset()
    ask_task = asyncio.create_task(controller.submit(prompt))
    try:
        while not callbacks.finished.is_set():
            queue_get = asyncio.create_task(callbacks.confirm_queue.get())
            done_wait = asyncio.create_task(callbacks.finished.wait())
            done, pending = await asyncio.wait(
                {queue_get, done_wait}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if queue_get in done:
                request_id, tool, risk, reason = queue_get.result()
                await _ask_confirm(controller, request_id, tool, risk, reason)
    finally:
        await ask_task


async def run_cli(client: OmniClient) -> int:
    """Readline REPL: type prompts, watch the stream; `exit` or Ctrl-D quits."""
    with contextlib.suppress(ImportError):
        import readline  # noqa: F401  (history/editing for input())

    callbacks = TtyCallbacks()
    controller = OmniController(client, callbacks)
    print("kow-omni (cli) — type a prompt, 'exit' or Ctrl-D to quit")
    while True:
        try:
            line = await asyncio.to_thread(_read_line, "kow> ")
        except KeyboardInterrupt:
            print()
            continue
        if line is None:  # Ctrl-D / EOF
            print()
            break
        prompt = line.strip()
        if not prompt:
            continue
        if prompt in ("exit", "quit"):
            break
        await _run_one(controller, callbacks, prompt)
    return 0
