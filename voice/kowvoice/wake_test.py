"""kow-voice wake-test: a live wake-word score meter. Plays a reference
pronunciation ("Скажите" + the word), then streams mic frames through the wake
model and draws the level + score bars; a chime fires on each detection, Space
replays the reference, q quits. Surfaces the mic/model errors the in-chat wake
loop would swallow, so it's the first stop when the wake word "doesn't react"."""

from __future__ import annotations

import sys

from .console import pr
from .settings import VoiceSettings


async def run_wake_test(settings=None) -> int:
    import importlib.util
    import os
    import select
    import termios
    import tty

    settings = settings or VoiceSettings.load()
    from .audio_devices import require_mic

    err = require_mic()
    if err:
        print(err, file=sys.stderr)
        return 2
    if importlib.util.find_spec("openwakeword") is None:
        print("wake word needs openWakeWord: pip install --no-deps openwakeword", file=sys.stderr)
        return 2
    model = settings.wake_model or settings.wake_word
    if not model:
        print("no wake model configured (set KOW_WAKE_MODEL or KOW_WAKE_WORD)", file=sys.stderr)
        return 2

    from .audio_devices import OpenWakeWordListener, SoundDeviceSink, quiet_alsa
    from .cues import load_clip
    from .tts_http import HttpTtsClient

    listener = OpenWakeWordListener(model, settings.sample_rate, settings.wake_threshold,
                                    device=settings.input_device)
    sink = SoundDeviceSink(device=settings.output_device)

    pr(f"wake-test: mic '{settings.input_device or 'system default'}', model '{model}', "
       f"threshold {settings.wake_threshold}.")

    # Spoken prompt synthesized once: "Скажите" (ru) + the word (en — the model's
    # training pronunciation). Network only here; the playback is below.
    phrase = settings.wake_word or "kowalski"
    say = ref = None
    try:
        say = await HttpTtsClient(settings.tts_url, settings.tts_token,
                                  language="ru").synthesize("Скажите")
        ref = await HttpTtsClient(settings.tts_url, settings.tts_token,
                                  language="en").synthesize(phrase)
    except Exception as exc:
        pr(f"(reference unavailable: {exc})")

    async def play(*clips) -> None:
        try:
            with quiet_alsa():  # keep ALSA's device-open chatter off the display
                for clip in clips:
                    if clip is not None:
                        await sink.play(clip)
        except Exception:
            pass

    bloop = load_clip("bloop.wav")  # success chime on each detection

    pr(f"Say '{phrase}'.  Space — replay '{phrase}', q — quit.")
    pr()
    await play(say, ref)  # full spoken prompt once: "Скажите" + the word

    peak = 0.0
    hits = 0
    armed = True  # ready to count/announce the next detection
    raw = sys.stdin.isatty()
    fd = sys.stdin.fileno()
    old_termios = termios.tcgetattr(fd) if raw else None
    if raw:
        tty.setcbreak(fd)
    try:
        async for scores, rms in listener.scores():
            if raw and select.select([fd], [], [], 0)[0]:
                ch = os.read(fd, 1)
                if ch in (b"q", b"\x03"):
                    break
                if ch == b" ":
                    sys.stdout.write("\r\033[K")
                    sys.stdout.flush()
                    await play(ref)  # Space replays just the word, no "Скажите"
            score = max(scores.values()) if scores else 0.0
            peak = max(peak, score)
            if score >= settings.wake_threshold:
                if armed:
                    armed, hits = False, hits + 1
                    if bloop is not None:
                        try:
                            await sink.play(bloop)
                        except Exception:
                            pass
            elif score < settings.wake_threshold * 0.5:
                armed = True  # re-arm once the score falls back down
            level = int(min(1.0, rms * 8) * 12)
            level_bar = "█" * level + "·" * (12 - level)
            score_n = int(min(1.0, score) * 20)
            score_bar = "█" * score_n + "·" * (20 - score_n)
            hit = f"  ◀ FIRE ✓{hits}" if score >= settings.wake_threshold else (
                f"  (✓{hits})" if hits else "")
            sys.stdout.write(
                f"\rmic [{level_bar}] {rms:.3f} │ score {score:.3f} [{score_bar}] "
                f"peak {peak:.3f}{hit}\033[K"
            )
            sys.stdout.flush()
    except Exception as exc:
        import traceback

        print(f"\nwake listener error: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        return 1
    finally:
        if raw:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_termios)
    return 0
