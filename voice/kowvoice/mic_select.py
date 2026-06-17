"""`kow-voice mic`: pick an input device with a live level meter + echo test.

Renders a small curses dialog: arrow-pick an input device, watch an RMS volume
bar move while you speak, run an echo test (record 2 s → play back), then save
the chosen device name to KOW_VOICE_INPUT_DEVICE. Reusable as a sub-dialog: pass
an existing `stdscr` (so the `kow setup` TUI can launch it without nesting
curses.wrapper), or call with none to run standalone."""

from __future__ import annotations

import sys

SAMPLE_RATE = 16000
BAR_WIDTH = 40


def run(stdscr=None) -> int:
    try:
        import sounddevice  # noqa: F401
    except Exception:
        print("microphone selection needs the mic extra: pip install -e 'voice[mic]'",
              file=sys.stderr)
        return 1
    import curses

    if stdscr is None:
        return curses.wrapper(_loop) or 0
    return _loop(stdscr) or 0


def _input_devices() -> list[tuple[int, str]]:
    import sounddevice as sd

    return [(i, d["name"]) for i, d in enumerate(sd.query_devices())
            if d.get("max_input_channels", 0) > 0]


def _current_name() -> str:
    from .settings import _kowalski_conf_path, _parse_conf

    return _parse_conf(_kowalski_conf_path()).get("KOW_VOICE_INPUT_DEVICE", "")


def _save(name: str) -> None:
    from kowalski.config import write_conf

    write_conf({"KOW_VOICE_INPUT_DEVICE": name})


def _echo_test(stdscr, device: int) -> str:
    """Record ~2 s from `device` and play it back on the default output."""
    import curses

    import numpy as np  # noqa: F401
    import sounddevice as sd

    try:
        _put(stdscr, "● recording 2 s — speak now…")
        rec = sd.rec(int(2 * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1,
                     device=device, dtype="float32")
        sd.wait()
        _put(stdscr, "▶ playing back…")
        sd.play(rec, SAMPLE_RATE)
        sd.wait()
        return "echo test done"
    except Exception as exc:  # noqa: BLE001 - surface any audio error in the dialog
        return f"echo failed: {exc}"
    finally:
        try:
            curses.flushinp()
        except Exception:
            pass


def _put(stdscr, msg: str) -> None:
    import curses

    try:
        stdscr.addstr(1, 2, msg + " " * 40, curses.A_BOLD)
        stdscr.refresh()
    except curses.error:
        pass


def _loop(stdscr) -> int:
    import curses

    import numpy as np
    import sounddevice as sd

    curses.curs_set(0)
    stdscr.timeout(60)  # ~16 fps meter refresh; getch returns -1 when idle

    devices = _input_devices()
    if not devices:
        stdscr.addstr(0, 2, "no input devices found — press a key")
        stdscr.timeout(-1)
        stdscr.getch()
        return 1

    cur = _current_name()
    sel = next((k for k, (_, n) in enumerate(devices) if cur and cur in n), 0)
    level = [0.0]
    stream = {"s": None}
    status = ""

    def close_stream():
        if stream["s"] is not None:
            try:
                stream["s"].stop()
                stream["s"].close()
            except Exception:
                pass
            stream["s"] = None

    def open_stream(idx: int) -> str:
        close_stream()

        def cb(indata, frames, t, s):
            try:
                level[0] = float(np.sqrt(np.mean(indata ** 2)))
            except Exception:
                level[0] = 0.0

        try:
            stream["s"] = sd.InputStream(device=idx, channels=1,
                                         samplerate=SAMPLE_RATE, callback=cb)
            stream["s"].start()
            return ""
        except Exception as exc:  # noqa: BLE001
            stream["s"] = None
            return f"cannot open device: {exc}"

    status = open_stream(devices[sel][0])
    try:
        while True:
            stdscr.erase()
            _safe(stdscr, 0, 2, "Select microphone", curses.A_BOLD)
            _safe(stdscr, 1, 2, "↑/↓ choose · e echo test · s save · q quit", curses.A_DIM)
            for k, (i, n) in enumerate(devices):
                mark = "●" if k == sel else " "
                attr = curses.A_REVERSE if k == sel else 0
                _safe(stdscr, 3 + k, 2, f"{mark} [{i:>2}] {n[:58]}", attr)
            row = 4 + len(devices)
            filled = int(min(1.0, level[0] * 15) * BAR_WIDTH)
            _safe(stdscr, row, 2, "level  " + "█" * filled + "·" * (BAR_WIDTH - filled))
            _safe(stdscr, row + 1, 2, "speak — the bar should move", curses.A_DIM)
            cur_mark = "current: " + (cur or "system default")
            _safe(stdscr, row + 3, 2, cur_mark, curses.A_DIM)
            if status:
                _safe(stdscr, row + 4, 2, status, curses.A_DIM)
            stdscr.refresh()

            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q"), 27):
                break
            if ch in (curses.KEY_UP, ord("k")):
                sel = (sel - 1) % len(devices)
                status = open_stream(devices[sel][0])
            elif ch in (curses.KEY_DOWN, ord("j")):
                sel = (sel + 1) % len(devices)
                status = open_stream(devices[sel][0])
            elif ch == ord("s"):
                _save(devices[sel][1])
                cur = devices[sel][1]
                status = f"saved: {devices[sel][1][:40]}"
            elif ch == ord("e"):
                close_stream()  # free the device for record/playback
                status = _echo_test(stdscr, devices[sel][0])
                open_stream(devices[sel][0])
    finally:
        close_stream()
    return 0


def _safe(stdscr, y: int, x: int, text: str, attr: int = 0) -> None:
    import curses

    try:
        stdscr.addstr(y, x, text, attr)
    except curses.error:
        pass


def main(argv: list[str] | None = None) -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
