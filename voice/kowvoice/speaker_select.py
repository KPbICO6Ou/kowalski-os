"""`kow-voice speaker`: pick the TTS output device and test it with a tone.

The output sibling of mic_select.py: arrow-pick an output device, play a short
test tone through it ("t"), then save the device name to KOW_VOICE_OUTPUT_DEVICE.
Reusable on a passed stdscr so the `kow setup` TUI can launch it."""

from __future__ import annotations

import sys

CONF_KEY = "KOW_VOICE_OUTPUT_DEVICE"


def run(stdscr=None) -> int:
    try:
        import sounddevice  # noqa: F401
    except Exception:
        print("output selection needs the mic extra: pip install -e 'voice[mic]'", file=sys.stderr)
        return 1
    import curses

    if stdscr is None:
        return curses.wrapper(_loop) or 0
    return _loop(stdscr) or 0


def _output_devices() -> list[tuple[int, str]]:
    import sounddevice as sd

    return [(i, d["name"]) for i, d in enumerate(sd.query_devices())
            if d.get("max_output_channels", 0) > 0]


def _current_name() -> str:
    from .settings import _kowalski_conf_path, _parse_conf

    return _parse_conf(_kowalski_conf_path()).get(CONF_KEY, "")


def _save(name: str) -> None:
    from kowalski.config import write_conf

    write_conf({CONF_KEY: name})


def _test_tone(stdscr, device: int) -> str:
    import numpy as np
    import sounddevice as sd

    from .mic_select import _put

    try:
        sr = int(sd.query_devices(device)["default_samplerate"]) or 44100
        _put(stdscr, "♪ playing test tone…")
        t = np.linspace(0, 0.6, int(sr * 0.6), endpoint=False)
        tone = (0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32")
        sd.play(tone, sr, device=device)
        sd.wait()
        return "tone played — did you hear it?"
    except Exception as exc:  # noqa: BLE001 - surface any audio error in the dialog
        return f"test failed: {exc}"


def _loop(stdscr) -> int:
    import curses

    from .mic_select import _safe

    curses.curs_set(0)
    stdscr.timeout(-1)

    devices = _output_devices()
    if not devices:
        _safe(stdscr, 0, 2, "no output devices found — press a key")
        stdscr.getch()
        return 1

    cur = _current_name()
    sel = next((k for k, (_, n) in enumerate(devices) if cur and cur in n), 0)
    status = ""
    while True:
        stdscr.erase()
        _safe(stdscr, 0, 2, "Select speaker / output", curses.A_BOLD)
        _safe(stdscr, 1, 2, "↑/↓ choose · t test tone · Enter/s save · q quit", curses.A_DIM)
        for k, (i, n) in enumerate(devices):
            mark = "●" if k == sel else " "
            attr = curses.A_REVERSE if k == sel else 0
            _safe(stdscr, 3 + k, 2, f"{mark} [{i:>2}] {n[:58]}", attr)
        row = 4 + len(devices)
        _safe(stdscr, row, 2, "current: " + (cur or "system default"), curses.A_DIM)
        if status:
            _safe(stdscr, row + 1, 2, status, curses.A_DIM)
        stdscr.refresh()

        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q"), 27):
            break
        if ch in (curses.KEY_UP, ord("k")):
            sel = (sel - 1) % len(devices)
        elif ch in (curses.KEY_DOWN, ord("j")):
            sel = (sel + 1) % len(devices)
        elif ch in (ord("t"), ord("e")):
            status = _test_tone(stdscr, devices[sel][0])
        elif ch in (ord("s"), curses.KEY_ENTER, 10, 13):
            _save(devices[sel][1])
            cur = devices[sel][1]
            status = f"✓ saved to config: {devices[sel][1][:40]}"
    return 0


def main(argv: list[str] | None = None) -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
