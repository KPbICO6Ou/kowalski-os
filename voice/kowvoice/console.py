"""Shared terminal presentation for the voice CLIs (chat, echo, wake-*): dim
styling, column-0-safe printing for a terminal left in raw/cbreak mode, a live
microphone level meter, and a dots progress line for slow STT/TTS calls."""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time

DIM = "\033[2m"
RESET = "\033[0m"

METER_LABELS = {"waiting": "speak…", "speaking": "hearing you…", "ending": "…"}


def pr(text: str = "") -> None:
    """Print a line anchored to column 0. A raw/cbreak reader can leave the
    cursor mid-line; a plain print() would then staircase across the screen."""
    sys.stdout.write("\r" + text + "\r\n")
    sys.stdout.flush()


def clear_line() -> None:
    """Erase the current line (tty only) — cleans up after an inline meter."""
    if sys.stdout.isatty():
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()


def mic_meter(rms: float, state: str) -> None:
    """Live mic-level bar on the current line (tty only) — the `on_level`
    callback for EnergyVadRecorder.record_utterance."""
    if not sys.stdout.isatty():
        return
    filled = int(min(1.0, rms * 16) * 16)
    bar = "█" * filled + "·" * (16 - filled)
    label = METER_LABELS.get(state, "")
    sys.stdout.write(f"\r{DIM}🎤 [{bar}] {label}{RESET}\033[K")
    sys.stdout.flush()


class Work:
    """A live progress line for a slow voice op (STT/TTS): cycles 1–3 dots
    ('TTS .' / '..' / '...') so the user sees something is happening, then
    rewrites the line as a summary 'TTS 123 chars (1.234s)'. The caller sets
    `.chars`; the elapsed time is measured around the `async with`. Animation is
    tty-only; the summary always prints (unless the body raised)."""

    def __init__(self, label: str, *, period: float = 0.35) -> None:
        self.label = label
        self.period = period
        self.chars = 0
        self.spin_task = None
        self.started_at = 0.0

    async def __aenter__(self) -> "Work":
        self.started_at = time.monotonic()
        if sys.stdout.isatty():
            self.spin_task = asyncio.ensure_future(self.spin())
        return self

    async def spin(self) -> None:
        dots = 0
        try:
            while True:
                dots = dots % 3 + 1
                sys.stdout.write(f"\r{DIM}{self.label} {'.' * dots}{RESET}\033[K")
                sys.stdout.flush()
                await asyncio.sleep(self.period)
        except asyncio.CancelledError:
            pass

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if self.spin_task is not None:
            self.spin_task.cancel()
            with contextlib.suppress(BaseException):
                await self.spin_task
        if exc_type is None:
            elapsed = time.monotonic() - self.started_at
            head, tail = ("\r", "\033[K") if sys.stdout.isatty() else ("", "")
            print(f"{head}{DIM}{self.label} {self.chars} chars ({elapsed:.3f}s){RESET}{tail}")
        return False
