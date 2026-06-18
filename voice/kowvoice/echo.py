"""kow-voice echo: a microphone + speaker round-trip test — say something after
the cue and hear it played straight back. Loops until Ctrl-C. Uses the configured
input/output devices, so it doubles as a quick check that those are right."""

from __future__ import annotations

import sys

DIM = "\033[2m"
RESET = "\033[0m"


def _meter(rms: float, state: str) -> None:
    if not sys.stdout.isatty():
        return
    filled = int(min(1.0, rms * 12) * 16)
    bar = "█" * filled + "·" * (16 - filled)
    label = {"waiting": "говорите…", "speaking": "слышу…", "ending": "…"}.get(state, "")
    sys.stdout.write(f"\r{DIM}  🎤 [{bar}] {label}{RESET}\033[K")
    sys.stdout.flush()


async def run_echo(settings=None) -> int:
    from .audio_devices import EnergyVadRecorder, SoundDeviceSink, _quiet_alsa
    from .cues import sound
    from .settings import VoiceSettings
    from .types import AudioClip

    settings = settings or VoiceSettings.load()
    recorder = EnergyVadRecorder(settings.sample_rate, settings.vad_silence_ms,
                                 device=settings.input_device, max_seconds=5.0)
    sink = SoundDeviceSink(device=settings.output_device)
    cue_path = sound("listen.wav")
    cue = AudioClip(audio=cue_path.read_bytes(), format="wav") if cue_path else None

    def pr(s: str = "") -> None:  # col-0 line, robust to a terminal left in raw mode
        sys.stdout.write("\r" + s + "\r\n")
        sys.stdout.flush()

    async def play(audio) -> None:
        if audio is None:
            return
        try:
            with _quiet_alsa():
                await sink.play(audio)
        except Exception as exc:
            pr(f"  (воспроизведение не удалось: {exc})")

    pr("Эхо-тест мик + динамик: скажите что-нибудь — повторю за вами. Ctrl-C — стоп.")
    pr(f"  мик: {settings.input_device or 'system default'} · "
       f"динамик: {settings.output_device or 'system default'}")
    while True:
        await play(cue)  # "speak now"
        try:
            utt = await recorder.record_utterance(on_level=_meter)
        except Exception as exc:
            pr(f"  (запись не удалась: {exc})")
            return 1
        if sys.stdout.isatty():
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        if utt is None or utt.is_empty:
            pr("  (тишина — говорите после сигнала)")
            continue
        dur = len(utt.pcm) / 2 / utt.sample_rate if utt.sample_rate else 0.0
        pr(f"  ↺ повторяю ({dur:.2f}s)…")
        await play(AudioClip(audio=utt.pcm, format="pcm", sample_rate=utt.sample_rate))
