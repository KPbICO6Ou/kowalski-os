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


def _test_tone(stdscr, device: int, name: str, bar_row: int) -> str:
    """Play a loud, distinctive 3-note chime and animate a progress bar while it
    plays, so it's obvious the test fired and on which device."""
    import time

    import numpy as np
    import sounddevice as sd

    from .mic_select import BAR_WIDTH, _safe

    try:
        sr = int(sd.query_devices(device)["default_samplerate"]) or 44100
        dur = 1.2
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        tone = np.zeros_like(t)
        for k, freq in enumerate((523.25, 659.25, 783.99)):  # C5–E5–G5
            seg = (t >= k * dur / 3) & (t < (k + 1) * dur / 3)
            tone[seg] = np.sin(2 * np.pi * freq * t[seg])
        sd.play((0.35 * tone).astype("float32"), sr, device=device)
        steps = 24
        for s in range(steps):
            filled = int(BAR_WIDTH * (s + 1) / steps)
            _safe(stdscr, bar_row, 2,
                  f"▶ playing on [{device}] {name[:26]}  " + "█" * filled + "·" * (BAR_WIDTH - filled))
            stdscr.refresh()
            time.sleep(dur / steps)
        sd.wait()
        return "tone done — heard it? (no sound → wrong output or nothing plugged into it)"
    except Exception as exc:  # noqa: BLE001 - surface any audio error in the dialog
        return f"test failed: {exc}"


def _loop(stdscr) -> int:
    import curses

    from .mic_select import _active_index, _default_device_index, _safe

    curses.curs_set(0)
    stdscr.timeout(-1)

    devices = _output_devices()
    if not devices:
        _safe(stdscr, 0, 2, "no output devices found — press a key")
        stdscr.getch()
        return 1

    cur = _current_name()
    default_out = _default_device_index(1)
    sel = next((k for k, (_, n) in enumerate(devices) if cur and cur in n), 0)
    status = ""
    while True:
        stdscr.erase()
        _safe(stdscr, 0, 2, "Select speaker / output", curses.A_BOLD)
        _safe(stdscr, 1, 2, "↑/↓ choose · t test tone · Enter/s save · q quit   (● = current)",
              curses.A_DIM)
        active = _active_index(devices, cur, default_out)
        for k, (i, n) in enumerate(devices):
            dot = "●" if k == active else " "
            attr = curses.A_REVERSE if k == sel else 0
            _safe(stdscr, 3 + k, 2, f"{dot} [{i:>2}] {n[:58]}", attr)
        row = 4 + len(devices)
        if cur:
            cur_name = cur
        elif active >= 0:
            cur_name = f"{devices[active][1]} (system default)"
        else:
            cur_name = "system default"
        _safe(stdscr, row, 2, "current: " + cur_name, curses.A_DIM)
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
            status = _test_tone(stdscr, devices[sel][0], devices[sel][1], row + 1)
        elif ch in (ord("s"), curses.KEY_ENTER, 10, 13):
            _save(devices[sel][1])
            cur = devices[sel][1]
            status = f"✓ saved to config: {devices[sel][1][:40]}"
    return 0


def main(argv: list[str] | None = None) -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
