"""Real microphone / playback adapters (Linux desktop). Everything here lazily
imports `sounddevice`/`numpy` (the `[mic]` extra) and needs actual audio
hardware, so none of it runs in CI — the orchestrator is exercised through the
mocks instead.

Wake word: a push-to-talk listener (waits for Enter) ships as the dependency-free
default; openWakeWord is the production upgrade (see `OpenWakeWordListener`).
Endpointing: a simple RMS energy VAD; silero-vad is the production upgrade."""

from __future__ import annotations

import asyncio

from .types import AudioClip, Utterance


class PushToTalkWake:
    """Dependency-free wake: press Enter to start a turn. Lets `kow-voice run`
    work on any Linux box before openWakeWord models are wired in."""

    async def wait_for_wake(self) -> None:
        await asyncio.get_running_loop().run_in_executor(None, input, "[press Enter to talk] ")


class OpenWakeWordListener:
    """Production wake word via openWakeWord (needs the [mic] extra + a model)."""

    def __init__(self, model: str, sample_rate: int = 16000) -> None:
        self.model = model
        self.sample_rate = sample_rate

    async def wait_for_wake(self) -> None:  # pragma: no cover - needs hardware + model
        raise NotImplementedError(
            "openWakeWord integration pending; use PushToTalkWake or `kow-voice demo`"
        )


class EnergyVadRecorder:
    """Capture from the default input device until a stretch of silence follows
    speech. RMS-based endpointing; replace with silero-vad for production."""

    def __init__(
        self, sample_rate: int = 16000, silence_ms: int = 700, threshold: float = 0.02
    ) -> None:
        self.sample_rate = sample_rate
        self.silence_ms = silence_ms
        self.threshold = threshold

    async def record_utterance(self) -> Utterance | None:  # pragma: no cover - needs a mic
        import numpy as np
        import sounddevice as sd

        block = int(self.sample_rate * 0.03)  # 30 ms blocks
        silence_blocks = max(1, self.silence_ms // 30)
        captured: list[bytes] = []
        trailing_silence = 0
        heard_speech = False

        loop = asyncio.get_running_loop()
        stream = sd.RawInputStream(
            samplerate=self.sample_rate, channels=1, dtype="int16", blocksize=block
        )
        stream.start()
        try:
            while True:
                data, _ = await loop.run_in_executor(None, stream.read, block)
                pcm = bytes(data)
                captured.append(pcm)
                rms = float(np.abs(np.frombuffer(pcm, dtype=np.int16) / 32768.0).mean())
                if rms >= self.threshold:
                    heard_speech = True
                    trailing_silence = 0
                elif heard_speech:
                    trailing_silence += 1
                    if trailing_silence >= silence_blocks:
                        break
        finally:
            stream.stop()
            stream.close()

        if not heard_speech:
            return None
        return Utterance(pcm=b"".join(captured), sample_rate=self.sample_rate)


class SoundDeviceSink:
    """Play a WAV/PCM AudioClip on the default output device; stop() interrupts."""

    def __init__(self) -> None:
        self._playing = False

    async def play(self, clip: AudioClip) -> None:  # pragma: no cover - needs audio out
        import io
        import wave

        import numpy as np
        import sounddevice as sd

        if clip.format == "wav":
            with wave.open(io.BytesIO(clip.audio), "rb") as wav:
                sample_rate = wav.getframerate()
                frames = wav.readframes(wav.getnframes())
        else:
            sample_rate = clip.sample_rate or 16000
            frames = clip.audio
        samples = np.frombuffer(frames, dtype=np.int16)
        self._playing = True
        sd.play(samples, sample_rate)
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, sd.wait)
        finally:
            self._playing = False

    async def stop(self) -> None:  # pragma: no cover - needs audio out
        import sounddevice as sd

        if self._playing:
            sd.stop()
            self._playing = False
