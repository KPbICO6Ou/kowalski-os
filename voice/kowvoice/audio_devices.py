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


def _resolve_device(device, want_output: bool):
    """Resolve a saved device name/substring to a sounddevice INDEX (what the mic
    picker opens with), since opening by the full name string is unreliable. None
    means the system default; an int is passed through. Never raises."""
    if device is None or device == "":
        return None
    if isinstance(device, int):
        return device
    try:
        import sounddevice as sd

        devices = sd.query_devices()
    except Exception:
        return None
    key = "max_output_channels" if want_output else "max_input_channels"
    for i, d in enumerate(devices):  # exact name first
        if d.get(key, 0) > 0 and d["name"] == device:
            return i
    for i, d in enumerate(devices):  # then substring
        if d.get(key, 0) > 0 and device.lower() in d["name"].lower():
            return i
    return None  # not found -> system default


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
        self, sample_rate: int = 16000, silence_ms: int = 700, threshold: float = 0.02,
        device: str = "", max_seconds: float = 15.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.silence_ms = silence_ms
        self.threshold = threshold
        self.device = device or None  # None = system default input
        self.max_seconds = max_seconds  # hard cap so a silent/wrong device can't hang

    async def record_utterance(self, on_level=None) -> Utterance | None:  # pragma: no cover
        import numpy as np
        import sounddevice as sd

        # Resolve a saved device name to an index (opening by full name is flaky).
        dev = _resolve_device(self.device, want_output=False)
        silence_blocks = max(1, self.silence_ms // 30)
        captured: list[bytes] = []
        trailing_silence = 0
        heard_speech = False
        loop = asyncio.get_running_loop()

        # Prefer 16 kHz (what STT wants); raw ALSA hw devices reject it, so fall
        # back to the device's native rate and resample the PCM afterwards.
        capture_sr = self.sample_rate
        block = int(capture_sr * 0.03)  # 30 ms blocks
        try:
            stream = sd.RawInputStream(samplerate=capture_sr, channels=1,
                                       dtype="int16", blocksize=block, device=dev)
            stream.start()
        except Exception:
            qd = dev if dev is not None else sd.default.device[0]
            capture_sr = int(sd.query_devices(qd)["default_samplerate"])
            block = int(capture_sr * 0.03)
            stream = sd.RawInputStream(samplerate=capture_sr, channels=1,
                                       dtype="int16", blocksize=block, device=dev)
            stream.start()

        max_blocks = max(1, int(self.max_seconds * capture_sr / block))
        calib_blocks = 8                  # ~240 ms to measure the noise floor
        noise: list[float] = []
        threshold = self.threshold        # refined from the noise floor below
        try:
            for n in range(max_blocks):
                data, _ = await loop.run_in_executor(None, stream.read, block)
                pcm = bytes(data)
                captured.append(pcm)
                samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0

                if not heard_speech and n < calib_blocks:
                    noise.append(rms)
                    if n == calib_blocks - 1:  # adapt to the mic: floor + noise-relative
                        threshold = max(sum(noise) / len(noise) * 3.0, 0.008)

                if rms >= threshold:
                    heard_speech = True
                    trailing_silence = 0
                elif heard_speech:
                    trailing_silence += 1
                state = ("ending" if trailing_silence else "speaking") if heard_speech else "waiting"
                if on_level is not None:
                    on_level(rms, state)
                if heard_speech and trailing_silence >= silence_blocks:
                    break
        finally:
            stream.stop()
            stream.close()

        if not heard_speech:
            return None
        samples = np.frombuffer(b"".join(captured), dtype=np.int16)
        if capture_sr != self.sample_rate and samples.size:
            n_out = int(samples.size * self.sample_rate / capture_sr)
            pos = np.linspace(0, samples.size - 1, n_out)
            samples = np.interp(pos, np.arange(samples.size), samples).astype(np.int16)
        return Utterance(pcm=samples.tobytes(), sample_rate=self.sample_rate)


class SoundDeviceSink:
    """Play a WAV/PCM AudioClip on the chosen output device; stop() interrupts."""

    def __init__(self, device: str = "") -> None:
        self._playing = False
        self.device = device or None  # None = system default output

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
        sd.play(samples, sample_rate, device=_resolve_device(self.device, want_output=True))
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
