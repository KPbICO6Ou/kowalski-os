"""OS seams: notifications and opening files/apps. Linux is the target,
macOS is the dev machine, everything else logs."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys

log = logging.getLogger(__name__)

IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


async def _run(cmd: list[str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    stdout, _ = await proc.communicate()
    return proc.returncode or 0, stdout.decode(errors="replace")


async def notify(title: str, body: str) -> bool:
    if IS_LINUX and shutil.which("notify-send"):
        code, _ = await _run(["notify-send", title, body])
        return code == 0
    if IS_MACOS:
        script = f'display notification "{_esc(body)}" with title "{_esc(title)}"'
        code, _ = await _run(["osascript", "-e", script])
        return code == 0
    log.info("notification: %s — %s", title, body)
    return False


async def open_path(target: str) -> tuple[bool, str]:
    """Open a file/directory/URL with the default application."""
    if IS_MACOS:
        code, out = await _run(["open", target])
    elif IS_LINUX and shutil.which("xdg-open"):
        code, out = await _run(["xdg-open", target])
    else:
        return False, "no opener available on this platform"
    return code == 0, out.strip()


async def open_app(name: str) -> tuple[bool, str]:
    """Launch an application by name."""
    if IS_MACOS:
        code, out = await _run(["open", "-a", name])
        return code == 0, out.strip()
    if IS_LINUX:
        if shutil.which("gtk-launch"):
            code, out = await _run(["gtk-launch", name])
            if code == 0:
                return True, out.strip()
        if shutil.which(name):
            proc = await asyncio.create_subprocess_exec(
                name, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            return proc.pid > 0, f"started pid {proc.pid}"
        return False, f"application not found: {name}"
    return False, "no launcher available on this platform"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')
