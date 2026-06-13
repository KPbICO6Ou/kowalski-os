"""kow-clip: an ambient clipboard watcher that asks the agent for a suggestion.

This is a *proactive* input source: it observes clipboard text the user copies
and, for meaningful selections, asks the agent for ONE short suggestion of the
most useful thing it could do with that text. The agent only SUGGESTS — it never
acts on the clipboard on its own — so this surface is safe to run in the
background. Suggestions are surfaced via a desktop notification and stdout.

Dependency-free: it shells out to the platform clipboard tool lazily
(``pbpaste`` on macOS, ``wl-paste`` on Wayland, ``xclip``/``xsel`` on X11) and
reuses the existing ``OmniClient`` socket client plus ``kowalski.platform``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable

from . import __version__
from .client import DaemonUnavailableError, OmniClient

log = logging.getLogger(__name__)

_PROMPT = (
    "The user just copied this text. In ONE short sentence, offer the single most "
    "useful thing you could do with it (do not do it yet):\n\n{text}"
)

OnSuggestion = Callable[[str, str], None | Awaitable[None]]


def _clipboard_command() -> list[str] | None:
    """Return the argv for reading the clipboard, or None if no tool is present.

    Order: macOS ``pbpaste``; Wayland ``wl-paste``; X11 ``xclip`` then ``xsel``.
    """
    if shutil.which("pbpaste"):
        return ["pbpaste"]
    if shutil.which("wl-paste"):
        return ["wl-paste", "--no-newline"]
    if shutil.which("xclip"):
        return ["xclip", "-selection", "clipboard", "-o"]
    if shutil.which("xsel"):
        return ["xsel", "-b"]
    return None


def read_clipboard() -> str | None:
    """Read clipboard text cross-platform, or None if unavailable.

    Returns None when no clipboard tool exists or the read fails. An empty
    clipboard yields an empty string.
    """
    cmd = _clipboard_command()
    if cmd is None:
        return None
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv from shutil.which
            cmd, capture_output=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("clipboard read failed: %s", exc)
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode(errors="replace")


class ClipboardWatcher:
    """Poll the clipboard and ask the agent for a suggestion on new text.

    When clipboard text changes to a new, non-empty value of length
    ``>= min_len`` (ignoring ``file://`` selections and respecting a per-fire
    ``cooldown``), the watcher asks the agent and invokes ``on_suggestion(text,
    answer)``. ``on_suggestion`` may be sync or async. Read/ask errors are logged
    and never propagate, so the loop keeps running.
    """

    def __init__(
        self,
        client: OmniClient,
        on_suggestion: OnSuggestion,
        poll: float = 1.2,
        min_len: int = 80,
        cooldown: float = 5.0,
        *,
        conversation_id: str | None = None,
        reader: Callable[[], str | None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._client = client
        self._on_suggestion = on_suggestion
        self._poll = poll
        self._min_len = min_len
        self._cooldown = cooldown
        self._conversation_id = conversation_id
        self._reader = reader or (lambda: read_clipboard())
        self._clock = clock or (lambda: asyncio.get_event_loop().time())
        self._last_text: str | None = None
        self._last_fire: float = float("-inf")
        self._task: asyncio.Task[None] | None = None

    def _is_meaningful(self, text: str | None) -> bool:
        if not text:
            return False
        stripped = text.strip()
        if len(stripped) < self._min_len:
            return False
        if stripped.startswith("file://"):
            return False
        return True

    async def _ask(self, text: str) -> str | None:
        """Ask the agent and return the DoneEvent answer, or None on error."""
        answer: str | None = None
        try:
            async for event in self._client.ask(
                _PROMPT.format(text=text), conversation_id=self._conversation_id
            ):
                kind = event.get("event")
                if kind == "DoneEvent":
                    answer = event.get("answer", "")
                elif kind == "ErrorEvent":
                    log.warning("agent error: %s", event.get("message", ""))
                    return None
        except DaemonUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 — never crash the watch loop
            log.warning("ask failed: %s", exc)
            return None
        return answer

    async def _cycle(self) -> bool:
        """Run one poll cycle. Returns True iff a suggestion was fired."""
        try:
            text = self._reader()
        except Exception as exc:  # noqa: BLE001 — robust against reader errors
            log.warning("clipboard read raised: %s", exc)
            return False

        if text == self._last_text:
            return False
        self._last_text = text

        if not self._is_meaningful(text):
            return False

        now = self._clock()
        if now - self._last_fire < self._cooldown:
            return False

        assert text is not None
        answer = await self._ask(text)
        if not answer:
            return False

        self._last_fire = now
        result = self._on_suggestion(text, answer)
        if asyncio.iscoroutine(result):
            await result
        return True

    async def _loop(self) -> None:
        while True:
            await self._cycle()
            await asyncio.sleep(self._poll)

    def start(self) -> asyncio.Task[None]:
        """Start the background polling task (idempotent)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
        return self._task

    async def stop(self) -> None:
        """Cancel the background polling task if running."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kow-clip", description="Kowalski clipboard suggestion watcher"
    )
    parser.add_argument("--version", action="version", version=f"kow-clip {__version__}")
    parser.add_argument("--socket", metavar="PATH", default=None, help="daemon socket path")
    parser.add_argument(
        "--min-len", type=int, default=80, help="minimum text length to consider (default 80)"
    )
    parser.add_argument(
        "--once", action="store_true", help="run a single poll cycle then exit (for testing)"
    )
    return parser


async def _emit(text: str, answer: str) -> None:
    """Print the suggestion and raise a desktop notification."""
    from kowalski import platform

    print(f"▶ {answer}")
    try:
        await platform.notify("Kowalski clipboard", answer)
    except Exception as exc:  # noqa: BLE001 — a failed toast must not break the loop
        log.warning("notify failed: %s", exc)


async def _amain(args: argparse.Namespace) -> int:
    client = OmniClient(socket_path=args.socket)
    watcher = ClipboardWatcher(client, _emit, min_len=args.min_len)
    try:
        if args.once:
            await watcher._cycle()
            return 0
        task = watcher.start()
        await task
    except DaemonUnavailableError as exc:
        print(
            f"kow-clip: {exc}\nStart the daemon with `kow serve`, then re-run kow-clip.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_amain(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
