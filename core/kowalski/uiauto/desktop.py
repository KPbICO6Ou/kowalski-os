"""The Desktop seam: a Protocol plus a real X11 adapter and a test double.

All adapters are async. The real adapter shells out to wmctrl/xdotool and
reads the accessibility tree via AT-SPI; everything OS-specific is lazily
imported so importing this module never drags in system dependencies."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Desktop(Protocol):
    """Window management + accessibility + input, async throughout."""

    async def list_windows(self) -> list[dict]:
        """Open windows as dicts: {id, title, app, active}."""
        ...

    async def activate_window(self, window_id: str) -> bool:
        """Focus/raise a window. Returns True on success."""
        ...

    async def accessibility_tree(self, window_id: str | None) -> dict:
        """Nested {role, name, children} tree for a window (or the active one
        when window_id is None)."""
        ...

    async def type_text(self, text: str) -> None:
        """Type literal text into the focused window."""
        ...

    async def press_keys(self, keys: str) -> None:
        """Press a key chord, xdotool key spec (e.g. 'ctrl+s', 'Return')."""
        ...

    async def click(self, x: int, y: int, button: int = 1) -> None:
        """Move the pointer to (x, y) and click the given button."""
        ...


# --------------------------------------------------------------------------- #
# Real adapter — Linux/X11 only, NOT exercised in CI.
# --------------------------------------------------------------------------- #


class XdotoolDesktop:
    """X11 adapter via wmctrl/xdotool and AT-SPI.

    Linux/X11 only — these binaries do not exist on the macOS dev box, so this
    class is never run in CI. Each method guards its dependency with
    shutil.which and raises an actionable error if it is missing.
    """

    @staticmethod
    async def _run(cmd: list[str]) -> tuple[int, str]:
        import asyncio

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        return proc.returncode or 0, stdout.decode(errors="replace")

    @staticmethod
    def _require(binary: str) -> None:
        import shutil

        if shutil.which(binary) is None:
            raise RuntimeError(
                f"'{binary}' not found on PATH; install it to use UI automation "
                f"(Linux/X11 only)."
            )

    async def list_windows(self) -> list[dict]:
        self._require("wmctrl")
        self._require("xdotool")
        code, out = await self._run(["wmctrl", "-l"])
        if code != 0:
            raise RuntimeError(f"wmctrl -l failed: {out.strip()}")
        active_id = await self._active_window_id()
        windows: list[dict] = []
        for line in out.splitlines():
            # format: <id> <desktop> <host> <title...>
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            win_id, _desktop, host, title = parts
            windows.append(
                {
                    "id": win_id,
                    "title": title,
                    "app": host,
                    "active": win_id.lower() == active_id.lower(),
                }
            )
        return windows

    async def _active_window_id(self) -> str:
        # xdotool reports decimal; wmctrl uses 0x-hex. Normalise to 0x-hex.
        code, out = await self._run(["xdotool", "getactivewindow"])
        if code != 0 or not out.strip():
            return ""
        try:
            return f"0x{int(out.strip()):08x}"
        except ValueError:
            return ""

    async def activate_window(self, window_id: str) -> bool:
        self._require("wmctrl")
        code, _ = await self._run(["wmctrl", "-ia", window_id])
        return code == 0

    async def accessibility_tree(self, window_id: str | None) -> dict:
        # AT-SPI is a Python binding (pyatspi), not a CLI; honest stub.
        try:
            import pyatspi  # noqa: F401
        except ImportError as exc:
            raise NotImplementedError(
                "accessibility_tree needs AT-SPI (python3-pyatspi); not available."
            ) from exc
        raise NotImplementedError(
            "AT-SPI tree walking is not implemented in this adapter yet."
        )

    async def type_text(self, text: str) -> None:
        self._require("xdotool")
        code, out = await self._run(["xdotool", "type", "--", text])
        if code != 0:
            raise RuntimeError(f"xdotool type failed: {out.strip()}")

    async def press_keys(self, keys: str) -> None:
        self._require("xdotool")
        code, out = await self._run(["xdotool", "key", "--", keys])
        if code != 0:
            raise RuntimeError(f"xdotool key failed: {out.strip()}")

    async def click(self, x: int, y: int, button: int = 1) -> None:
        self._require("xdotool")
        code, out = await self._run(["xdotool", "mousemove", str(x), str(y)])
        if code != 0:
            raise RuntimeError(f"xdotool mousemove failed: {out.strip()}")
        code, out = await self._run(["xdotool", "click", str(button)])
        if code != 0:
            raise RuntimeError(f"xdotool click failed: {out.strip()}")


# --------------------------------------------------------------------------- #
# Test double — scripted, records all mutations.
# --------------------------------------------------------------------------- #


class MockDesktop:
    """Scripted Desktop for tests: serves canned windows/tree and records
    every activation, typed string, key chord, and click."""

    def __init__(
        self,
        windows: list[dict] | None = None,
        tree: dict | None = None,
    ):
        self._windows = windows if windows is not None else []
        self._tree = tree if tree is not None else {"role": "application", "name": "", "children": []}
        self.activated: list[str] = []
        self.typed: list[str] = []
        self.pressed: list[str] = []
        self.clicks: list[tuple[int, int, int]] = []

    async def list_windows(self) -> list[dict]:
        return [dict(w) for w in self._windows]

    async def activate_window(self, window_id: str) -> bool:
        self.activated.append(window_id)
        return any(w.get("id") == window_id for w in self._windows)

    async def accessibility_tree(self, window_id: str | None) -> dict:
        return self._tree

    async def type_text(self, text: str) -> None:
        self.typed.append(text)

    async def press_keys(self, keys: str) -> None:
        self.pressed.append(keys)

    async def click(self, x: int, y: int, button: int = 1) -> None:
        self.clicks.append((x, y, button))
