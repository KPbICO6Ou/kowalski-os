"""kow-voice echo: a microphone + speaker round-trip test — say something after
the cue and hear it played straight back. Loops until Ctrl-C. Uses the configured
input/output devices, so it doubles as a quick check that those are right."""

from __future__ import annotations


from .console import clear_line, mic_meter, pr


async def run_echo(settings=None) -> int:
    from .audio_devices import EnergyVadRecorder, SoundDeviceSink, _quiet_alsa
    from .cues import load_clip
    from .settings import VoiceSettings
    from .types import AudioClip

    settings = settings or VoiceSettings.load()
    recorder = EnergyVadRecorder(settings.sample_rate, settings.vad_silence_ms,
                                 device=settings.input_device, max_seconds=5.0)
    sink = SoundDeviceSink(device=settings.output_device)
    cue = load_clip("listen.wav")

    async def play(audio) -> None:
        if audio is None:
            return
        try:
            with _quiet_alsa():
                await sink.play(audio)
        except Exception as exc:
            pr(f"  (playback failed: {exc})")

    pr("Echo test (mic + speaker): say something and hear it back. Ctrl-C to stop.")
    pr(f"  mic: {settings.input_device or 'system default'} · "
       f"speaker: {settings.output_device or 'system default'}")
    while True:
        await play(cue)  # "speak now"
        try:
            utt = await recorder.record_utterance(on_level=mic_meter)
        except Exception as exc:
            pr(f"  (recording failed: {exc})")
            return 1
        clear_line()
        if utt is None or utt.is_empty:
            pr("  (silence — speak after the cue)")
            continue
        dur = len(utt.pcm) / 2 / utt.sample_rate if utt.sample_rate else 0.0
        pr(f"  ↺ playing back ({dur:.2f}s)…")
        await play(AudioClip(audio=utt.pcm, format="pcm", sample_rate=utt.sample_rate))
