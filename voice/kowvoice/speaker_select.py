"""`kow-voice speaker`: pick the TTS output device and test it by holding `t`.

The output sibling of mic_select.py: arrow-pick an output device; **hold `t`** to
play a continuous tone whose volume ramps up the longer you hold (a live volume
bar at the bottom, like the mic level meter), release to fade out; then save the
device name to KOW_VOICE_OUTPUT_DEVICE. Reusable on a passed stdscr."""

from __future__ import annotations

import sys

CONF_KEY = "KOW_VOICE_OUTPUT_DEVICE"
FREQ = 440.0          # test-tone frequency (A4)
VOL_MAX = 0.7         # peak amplitude
RAMP_UP_PER_SEC = 0.5  # how fast the volume rises while held
RAMP_DN_PER_SEC = 1.5  # how fast it fades on release
HOLD_EXTEND = 0.7      # each `t` keeps the tone alive this long (covers key-repeat gaps)


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


def _loop(stdscr) -> int:
    import time

    import curses

    import numpy as np
    import sounddevice as sd

    from .mic_select import BAR_WIDTH, _active_index, _default_device_index, _safe

    curses.curs_set(0)
    stdscr.timeout(40)  # ~25 fps; getch returns -1 when idle so the ramp keeps moving

    devices = _output_devices()
    if not devices:
        _safe(stdscr, 0, 2, "no output devices found — press a key")
        stdscr.timeout(-1)
        stdscr.getch()
        return 1

    cur = _current_name()
    default_out = _default_device_index(1)
    sel = next((k for k, (_, n) in enumerate(devices) if cur and cur in n), 0)

    volume = [0.0]
    phase = [0.0]
    play_until = [0.0]
    stream = {"s": None}

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
        try:
            sr = int(sd.query_devices(idx)["default_samplerate"]) or 48000
        except Exception:
            sr = 48000

        def cb(outdata, frames, t, status):  # runs in sounddevice's audio thread
            try:
                i = np.arange(frames)
                ph = phase[0] + 2 * np.pi * FREQ * i / sr
                outdata[:] = (volume[0] * np.sin(ph)).astype("float32").reshape(-1, 1)
                phase[0] = float((ph[-1] + 2 * np.pi * FREQ / sr) % (2 * np.pi))
            except Exception:
                outdata[:] = 0

        last_exc: Exception | None = None
        for channels in (1, 2):
            try:
                stream["s"] = sd.OutputStream(device=idx, channels=channels,
                                              samplerate=sr, callback=cb)
                stream["s"].start()
                return ""
            except Exception as exc:  # noqa: BLE001
                stream["s"] = None
                last_exc = exc
        return f"cannot open device: {last_exc}"

    status = open_stream(devices[sel][0])
    last = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            dt, last = now - last, now

            stdscr.erase()
            _safe(stdscr, 0, 2, "Select speaker / output", curses.A_BOLD)
            _safe(stdscr, 1, 2,
                  "↑/↓ choose · hold t to test (volume ramps) · Enter/s save · q quit   (● = current)",
                  curses.A_DIM)
            active = _active_index(devices, cur, default_out)
            for k, (i, n) in enumerate(devices):
                dot = "●" if k == active else " "
                attr = curses.A_REVERSE if k == sel else 0
                _safe(stdscr, 3 + k, 2, f"{dot} [{i:>2}] {n[:58]}", attr)
            row = 4 + len(devices)
            filled = int(min(1.0, volume[0] / VOL_MAX) * BAR_WIDTH)
            _safe(stdscr, row, 2, "volume " + "█" * filled + "·" * (BAR_WIDTH - filled))
            _safe(stdscr, row + 1, 2, "hold t — the tone plays and gets louder", curses.A_DIM)
            if cur:
                cur_name = cur
            elif active >= 0:
                cur_name = f"{devices[active][1]} (system default)"
            else:
                cur_name = "system default"
            _safe(stdscr, row + 3, 2, "current: " + cur_name, curses.A_DIM)
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
            elif ch in (ord("t"), ord("e")):
                play_until[0] = now + HOLD_EXTEND  # held while key-repeat keeps extending it
            elif ch in (ord("s"), curses.KEY_ENTER, 10, 13):
                _save(devices[sel][1])
                cur = devices[sel][1]
                status = f"✓ saved to config: {devices[sel][1][:40]}"

            if now < play_until[0]:
                volume[0] = min(VOL_MAX, volume[0] + RAMP_UP_PER_SEC * dt)
            else:
                volume[0] = max(0.0, volume[0] - RAMP_DN_PER_SEC * dt)
    finally:
        volume[0] = 0.0
        close_stream()
    return 0


def main(argv: list[str] | None = None) -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
