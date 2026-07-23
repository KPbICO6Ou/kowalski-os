"""kow-voice wake-record: capture real spoken samples of a wake phrase to train a
personal openWakeWord model on (see kow-voice wake-fit). Records the user's own
natural pronunciation — positives (the phrase) and negatives (other speech) — with
audio cues (a chime = speak now, a chime = good take, a buzz = retry), validates
each take (speech present, sane length, not silent), and saves WAVs under
~/.config/kowalski/wake/samples/<slug>/."""

from __future__ import annotations

from pathlib import Path

from .console import clear_line, mic_meter, pr


def samples_dir(slug: str) -> Path:
    return Path("~/.config/kowalski/wake/samples").expanduser() / slug


def validate_take(utt) -> tuple[bool, str]:
    """A take is usable if it caught speech of a word's length at an audible level."""
    if utt is None or utt.is_empty:
        return False, "no speech"
    import numpy as np

    pcm = np.frombuffer(utt.pcm, dtype=np.int16).astype(np.float32) / 32768.0
    dur = pcm.size / utt.sample_rate if utt.sample_rate else 0.0
    rms = float(np.sqrt(np.mean(pcm * pcm))) if pcm.size else 0.0
    if dur < 0.3:
        return False, f"too short ({dur:.2f}s)"
    if dur > 2.5:
        return False, f"too long ({dur:.2f}s)"
    if rms < 0.012:
        return False, f"too quiet (rms {rms:.3f})"
    return True, f"{dur:.2f}s · rms {rms:.3f}"


async def run_record(phrase: str, *, count: int = 30, negatives: int = 12,
                     settings=None) -> int:
    from .audio_devices import EnergyVadRecorder, SoundDeviceSink, quiet_alsa
    from .cues import load_clip
    from .settings import VoiceSettings
    from .stt_http import pcm_to_wav
    from .train import slugify
    from .tts_http import HttpTtsClient

    settings = settings or VoiceSettings.load()
    slug = slugify(phrase)
    pos_dir = samples_dir(slug) / "positive"
    neg_dir = samples_dir(slug) / "negative"
    pos_dir.mkdir(parents=True, exist_ok=True)
    neg_dir.mkdir(parents=True, exist_ok=True)

    recorder = EnergyVadRecorder(settings.sample_rate, settings.vad_silence_ms,
                                 device=settings.input_device, max_seconds=3.0)
    sink = SoundDeviceSink(device=settings.output_device)

    cue, ok, nope = load_clip("listen.wav"), load_clip("bloop.wav"), load_clip("oops.wav")

    async def play(audio) -> None:
        if audio is None:
            return
        try:
            with quiet_alsa():
                await sink.play(audio)
        except Exception:
            pass

    async def announce(text: str, lang: str = "ru") -> None:
        """Spoken (TTS) prompt — kept in the user's language; console text is English."""
        try:
            await play(await HttpTtsClient(settings.tts_url, settings.tts_token,
                                           language=lang).synthesize(text))
        except Exception:
            pass

    async def capture(prompt: str, dest: Path, idx: int) -> bool:
        pr(prompt)
        await play(cue)  # the "speak now" signal
        utt = await recorder.record_utterance(on_level=mic_meter)
        clear_line()
        valid, info = validate_take(utt)
        if valid:
            (dest / f"{idx:03d}.wav").write_bytes(pcm_to_wav(utt.pcm, utt.sample_rate))
            await play(ok)
            pr(f"  ✓ {info}")
            return True
        await play(nope)
        pr(f"  ✗ {info} — again")
        return False

    pr(f"Recording '{phrase}' for training — {count} clear takes.")
    pr("Say the word after each chime, the way you normally would. Ctrl-C to stop.")
    await announce(f"Запишем слово {phrase}. После каждого сигнала произнесите его.")

    got = 0
    try:
        while got < count:
            if await capture(f"[{got + 1}/{count}] say '{phrase}' after the chime:",
                             pos_dir, got):
                got += 1

        pr("")
        pr(f"Now negatives — say OTHER words/phrases (NOT '{phrase}').")
        await announce(f"Теперь говорите другие фразы, кроме {phrase}.")
        neg = 0
        while neg < negatives:
            if await capture(f"[neg {neg + 1}/{negatives}] any other phrase:",
                             neg_dir, neg):
                neg += 1
    except (KeyboardInterrupt, EOFError):
        pr("")
        pr("(interrupted)")

    npos = len(list(pos_dir.glob("*.wav")))
    nneg = len(list(neg_dir.glob("*.wav")))
    pr("")
    pr(f"Done: {npos} positives, {nneg} negatives -> {samples_dir(slug)}")
    pr(f"Next: kow-voice wake-fit {phrase}")
    return 0
