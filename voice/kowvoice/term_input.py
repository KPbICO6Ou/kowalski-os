"""Raw-terminal input for the unified chat: a cbreak line reader that can be
polled/cancelled (so typing can be raced against the wake word), an in-chat
hotkey decoder, and the TALK/STOP sentinels the reader returns. Kept free of
audio/agent imports — this is stdin/termios only."""

from __future__ import annotations

TALK = object()  # sentinel: the raw reader returns this when the hotkey is pressed
STOP = object()  # sentinel: the raw reader was cancelled (stop event set, e.g. wake fired)

MOD_NAMES = {"ctrl": "Ctrl", "control": "Ctrl", "alt": "Alt", "shift": "Shift",
             "super": "Super", "win": "Super", "meta": "Super", "cmd": "Cmd"}


def fmt_hotkey(combo: str) -> str:
    """Pretty-print a 'mod+key' combo for the banner, e.g. 'alt+v' -> 'Alt+v'."""
    return "+".join(MOD_NAMES.get(p.lower(), p) for p in combo.split("+"))


def hotkey_bytes(combo: str) -> bytes | None:
    """The bytes a terminal sends for an in-chat-usable hotkey, or None when the
    combo can't be one: a plain key collides with typing, and Shift/Super on
    printable keys aren't terminal-readable (use the global XFCE binding for those)."""
    if not combo:
        return None
    parts = [p.lower() for p in combo.split("+")]
    mods, key = parts[:-1], parts[-1]
    if not mods or any(m in ("shift", "super", "win", "meta", "cmd") for m in mods):
        return None
    if "ctrl" in mods or "control" in mods:
        if key == "space":
            seq = b"\x00"
        elif len(key) == 1 and key.isalpha():
            seq = bytes([ord(key) & 0x1F])
        else:
            return None
    elif len(key) == 1:
        seq = key.encode()
    else:
        return None
    return b"\x1b" + seq if "alt" in mods else seq


def peek_byte(fd: int, timeout: float = 0.06) -> int | None:
    import os
    import select

    if select.select([fd], [], [], timeout)[0]:
        b = os.read(fd, 1)
        return b[0] if b else None
    return None


def raw_read(prompt: str, hotkey: bytes | None, stop=None):
    """cbreak line reader: returns the typed line, TALK on the hotkey; raises
    EOFError on Ctrl-D (empty) and KeyboardInterrupt on Ctrl-C. Basic editing
    only (printable + UTF-8 + Backspace); no history/arrows.

    When `stop` (a threading.Event) is given, the read polls instead of blocking
    so the worker can be cancelled (returns STOP) — used to race typing against
    the wake word without orphaning a stuck os.read."""
    import os
    import select
    import sys
    import termios
    import tty

    fd = sys.stdin.fileno()
    sys.stdout.write(prompt)
    sys.stdout.flush()
    old = termios.tcgetattr(fd)
    buf: list[str] = []
    try:
        tty.setcbreak(fd)  # ICANON+ECHO off, ISIG on (Ctrl-C still raises)
        while True:
            if stop is not None:
                while not (stop.is_set() or select.select([fd], [], [], 0.1)[0]):
                    pass
                if stop.is_set():
                    return STOP
            c = os.read(fd, 1)
            if not c:
                raise EOFError
            b = c[0]
            if b in (10, 13):  # Enter
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                return "".join(buf)
            if b == 4:  # Ctrl-D
                if not buf:
                    raise EOFError
                continue
            if b in (8, 127):  # Backspace
                if buf:
                    buf.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if b == 27:  # Esc: Alt-hotkey or an escape sequence
                nxt = peek_byte(fd)
                if hotkey and hotkey[:1] == b"\x1b" and nxt is not None and nxt == hotkey[1]:
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    return TALK
                if nxt == 0x5B:  # '[' -> consume the arrow/seq final byte
                    peek_byte(fd)
                continue
            if hotkey and len(hotkey) == 1 and b == hotkey[0]:  # ctrl-* hotkey
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                return TALK
            if 32 <= b < 127:  # printable ASCII
                buf.append(chr(b))
                sys.stdout.write(chr(b))
                sys.stdout.flush()
            elif b >= 0xC0:  # UTF-8 lead byte (e.g. Cyrillic) -> read the rest
                n = 2 if b < 0xE0 else 3 if b < 0xF0 else 4
                rest = b"".join(os.read(fd, 1) for _ in range(n - 1))
                try:
                    ch = (bytes([b]) + rest).decode("utf-8")
                    buf.append(ch)
                    sys.stdout.write(ch)
                    sys.stdout.flush()
                except Exception:
                    pass
            # other control bytes ignored (Ctrl-C arrives as SIGINT via ISIG)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def reader_for(hotkey: bytes | None):
    """A line reader bound to a precomputed hotkey (returns TALK when pressed)."""
    return lambda prompt: raw_read(prompt, hotkey)
