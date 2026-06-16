"""Real microphone / playback adapters (Linux desktop). Everything here lazily
imports `sounddevice`/`numpy` (the `[mic]` extra) and needs actual audio
hardware, so none of it runs in CI — the orchestrator is exercised through the
mocks instead.

Wake word: a push-to-talk listener (waits for Enter) ships as the dependency-free
default; openWakeWord is the production upgrade (see `OpenWakeWordListener`).
Endpointing: a simple RMS energy VAD; silero-vad is the production upgrade."""

from __future__ import annotations

import asyncio
import contextlib

from .types import AudioClip, Utterance


class PushToTalkWake:
    """Dependency-free wake: press Enter to start a turn. Works on any box and
    is the fallback half of the `both` wake mode."""

    async def wait_for_wake(self) -> None:
        await asyncio.get_running_loop().run_in_executor(None, input, "[press Enter to talk] ")


class OpenWakeWordListener:
    """Spoken wake word via openWakeWord (needs the [mic] extra).

    `model` is either a pretrained model name openWakeWord ships/downloads
    (e.g. "hey_jarvis", "alexa") or a path to a custom .onnx/.tflite model. A
    bespoke phrase such as "kowalski" requires a trained model file — point
    `model` at its path."""

    def __init__(self, model: str, sample_rate: int = 16000, threshold: float = 0.5) -> None:
        self.model = model
        self.sample_rate = sample_rate
        self.threshold = threshold
        self._oww = None

    def _load(self):
        # ONNX is the default framework: openWakeWord pins tflite-runtime, which
        # has no Python 3.12 wheel, so we install openWakeWord --no-deps with
        # onnxruntime and run the .onnx model variants. Only an explicit .tflite
        # path opts into tflite.
        from openwakeword.model import Model

        model = self.model
        if model.endswith(".tflite"):
            return Model(wakeword_models=[model], inference_framework="tflite")
        if model:
            return Model(wakeword_models=[model], inference_framework="onnx")
        return Model(inference_framework="onnx")

    async def wait_for_wake(self) -> None:  # pragma: no cover - needs hardware + model
        import numpy as np
        import sounddevice as sd

        if self._oww is None:
            self._oww = self._load()

        frame = 1280  # openWakeWord expects 80 ms frames at 16 kHz
        loop = asyncio.get_running_loop()
        stream = sd.RawInputStream(
            samplerate=self.sample_rate, channels=1, dtype="int16", blocksize=frame
        )
        stream.start()
        try:
            while True:
                data, _ = await loop.run_in_executor(None, stream.read, frame)
                pcm = np.frombuffer(bytes(data), dtype=np.int16)
                scores = self._oww.predict(pcm)
                if scores and max(scores.values()) >= self.threshold:
                    return
        finally:
            stream.stop()
            stream.close()


class CombinedWake:
    """Fire when ANY of the wrapped listeners fires (push-to-talk OR wake word).

    A listener that errors (e.g. openWakeWord can't load its model) is dropped so
    the surviving listeners keep working; if every listener errors, the first
    error is raised."""

    def __init__(self, listeners) -> None:
        self.listeners = list(listeners)

    async def wait_for_wake(self) -> None:
        tasks = [asyncio.create_task(listener.wait_for_wake()) for listener in self.listeners]
        errors: list[BaseException] = []
        try:
            pending = set(tasks)
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    exc = task.exception()
                    if exc is None:
                        return
                    errors.append(exc)
            raise errors[0]
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
                with contextlib.suppress(BaseException):
                    await task


def build_wake(settings):
    """Pick the wake listener from settings.wake_mode."""
    mode = (settings.wake_mode or "push_to_talk").lower()
    if mode == "push_to_talk":
        return PushToTalkWake()
    model = settings.wake_model or settings.wake_word
    oww = OpenWakeWordListener(model, settings.sample_rate, settings.wake_threshold)
    if mode == "wake_word":
        return oww
    if mode == "both":
        return CombinedWake([PushToTalkWake(), oww])
    return PushToTalkWake()


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
