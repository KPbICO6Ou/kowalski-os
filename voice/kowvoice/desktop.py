"""Best-effort X11 helper: bring the terminal that hosts this process to the
foreground. Used when a hands-free wake/hotkey turn starts so the `kow chat`
dialog window comes to the screen. Everything here is best-effort and no-ops
without `$DISPLAY` or `wmctrl`/`xdotool`, so headless boxes, macOS, and CI are
unaffected. Pattern mirrors core's XdotoolDesktop.activate_window (wmctrl -ia)."""

from __future__ import annotations

import os
import shutil
import subprocess


def _process_chain(limit: int = 6) -> list[str]:
    """This PID and its ancestors (the terminal is usually a parent), as strings."""
    pids: list[str] = []
    pid = os.getpid()
    for _ in range(limit):
        if pid <= 1:
            break
        pids.append(str(pid))
        try:
            with open(f"/proc/{pid}/stat") as stat:
                pid = int(stat.read().split()[3])  # field 4 = ppid
        except Exception:
            break
    return pids


def _own_window_id_hex() -> str | None:
    """The X11 window id (0x-hex) of the terminal hosting this process, or None.
    Tries $WINDOWID (xterm-style), then matches our process chain in `wmctrl -lp`."""
    wid = os.environ.get("WINDOWID", "").strip()
    if wid.isdigit() and int(wid) > 0:
        return f"0x{int(wid):08x}"
    if shutil.which("wmctrl"):
        pids = set(_process_chain())
        try:
            out = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True,
                                  timeout=2, check=False).stdout
        except Exception:
            out = ""
        for line in out.splitlines():
            parts = line.split(None, 4)  # winid desktop pid host title
            if len(parts) >= 3 and parts[2] in pids:
                return parts[0]
    return None


def raise_own_window() -> bool:
    """Un-minimize + focus the terminal hosting this process. Best-effort; returns
    True if a raise command was issued, False if there's nothing to do (no display,
    no tools, or no matching window). Never raises."""
    if not os.environ.get("DISPLAY"):
        return False
    if shutil.which("wmctrl"):
        wid = _own_window_id_hex()
        if wid:
            try:
                subprocess.run(["wmctrl", "-i", "-a", wid], timeout=2, check=False)
                return True
            except Exception:
                pass
    if shutil.which("xdotool"):
        for pid in _process_chain():
            try:
                result = subprocess.run(
                    ["xdotool", "search", "--pid", pid, "windowactivate"],
                    capture_output=True, timeout=2, check=False)
            except Exception:
                continue
            if result.returncode == 0:
                return True
    return False
