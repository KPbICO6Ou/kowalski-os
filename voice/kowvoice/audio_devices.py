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
import os

from .types import AudioClip, Utterance


@contextlib.contextmanager
def _quiet_alsa():
    """Hide PortAudio/ALSA's C-level probe chatter (it writes to fd 2 directly,
    e.g. paInvalidSampleRate when we try 16 kHz on a raw hw device)."""
    try:
        saved, devnull = os.dup(2), os.open(os.devnull, os.O_WRONLY)
    except OSError:
        yield
        return
    os.dup2(devnull, 2)
    try:
        yield
    finally:
        os.dup2(saved, 2)
        os.close(devnull)
        os.close(saved)


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


def _open_capture(device, target_sr: int, block_ms: int):
    """Open a callback-mode int16 mono input stream; return
    (stream, frames_queue, capture_sr, block_samples).

    Callback mode — PortAudio owns the capture thread and delivers frames via a
    queue — instead of a blocking `stream.read()` in an executor thread. That read
    could still be running in its thread when teardown called `stream.close()` from
    another thread on Ctrl-C, corrupting ALSA's mmap state and segfaulting (the
    `alsa_snd_pcm_mmap_begin ... failed` crash). Here `close()` just joins
    PortAudio's own thread and nothing races it.

    Prefers `target_sr`; a raw hw device that rejects it falls back to the device's
    native rate (the caller resamples)."""
    import queue

    import sounddevice as sd

    frames: queue.Queue = queue.Queue(maxsize=64)

    def callback(indata, count, time_info, status):  # PortAudio thread
        try:
            frames.put_nowait(bytes(indata))
        except queue.Full:
            pass  # drop on overflow rather than block the audio callback

    def _start(sr: int):
        block = max(1, int(sr * block_ms / 1000))
        stream = sd.RawInputStream(samplerate=sr, channels=1, dtype="int16",
                                   blocksize=block, device=device, callback=callback)
        stream.start()
        return stream, block

    with _quiet_alsa():  # a hw device rejecting target_sr is expected, not noise
        try:
            stream, block = _start(target_sr)
            return stream, frames, target_sr, block
        except Exception:
            qd = device if device is not None else sd.default.device[0]
            native = int(sd.query_devices(qd)["default_samplerate"])
            stream, block = _start(native)
            return stream, frames, native, block


async def _next_frame(loop, frames):
    """Await the next captured chunk (bytes), or None if the mic stalled for ~1 s
    (so a dead device can't block forever and cancellation stays responsive)."""
    import queue

    try:
        return await loop.run_in_executor(None, frames.get, True, 1.0)
    except queue.Empty:
        return None


def _close_capture(stream) -> None:
    """Tear down a capture stream, swallowing teardown errors."""
    with contextlib.suppress(Exception):
        stream.stop()
    with contextlib.suppress(Exception):
        stream.close()


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

    def __init__(self, model: str, sample_rate: int = 16000, threshold: float = 0.5,
                 device: str = "") -> None:
        self.model = model
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.device = device or None  # None = system default input
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

    async def _frames(self):  # pragma: no cover - needs hardware
        """Yield 16 kHz int16 frames (~80 ms) from the configured input device.
        Opens at 16 kHz (what openWakeWord wants); a raw hw device that rejects it
        falls back to the native rate + linear resample, like EnergyVadRecorder."""
        import numpy as np

        dev = _resolve_device(self.device, want_output=False)
        stream, frames, capture_sr, _ = _open_capture(dev, 16000, 80)  # ~80 ms frames
        loop = asyncio.get_running_loop()
        try:
            while True:
                data = await _next_frame(loop, frames)
                if data is None:
                    continue
                pcm = np.frombuffer(data, dtype=np.int16)
                if capture_sr != 16000 and pcm.size:
                    n_out = int(pcm.size * 16000 / capture_sr)
                    pos = np.linspace(0, pcm.size - 1, n_out)
                    pcm = np.interp(pos, np.arange(pcm.size), pcm).astype(np.int16)
                yield pcm
        finally:
            _close_capture(stream)

    async def wait_for_wake(self) -> None:  # pragma: no cover - needs hardware + model
        import os
        import sys

        debug = os.getenv("KOW_WAKE_DEBUG", "").strip().lower() not in ("", "0", "false", "no")
        if self._oww is None:
            self._oww = self._load()
        last = 0.0
        async for pcm in self._frames():
            scores = self._oww.predict(pcm)
            top = max(scores.values()) if scores else 0.0
            if debug and (top >= 0.1 and abs(top - last) >= 0.05):
                last = top
                print(f"[wake] score={top:.2f} (fires at {self.threshold})",
                      file=sys.stderr, flush=True)
            if top >= self.threshold:
                if debug:
                    print(f"[wake] FIRE score={top:.2f}", file=sys.stderr, flush=True)
                return

    async def scores(self):  # pragma: no cover - needs hardware + model
        """Yield ({model: score}, input_rms) per frame — for live diagnostics. The
        RMS tells a dead mic (capture/device problem) from a quiet model (the
        audio is there but the word doesn't match)."""
        import numpy as np

        if self._oww is None:
            self._oww = self._load()
        async for pcm in self._frames():
            rms = (float(np.sqrt(np.mean((pcm.astype(np.float32) / 32768.0) ** 2)))
                   if pcm.size else 0.0)
            yield self._oww.predict(pcm), rms


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
    oww = OpenWakeWordListener(model, settings.sample_rate, settings.wake_threshold,
                               device=settings.input_device)
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
        device: str = "", max_seconds: float = 15.0, onset_timeout: float = 3.0,
        min_speech_ms: int = 200,
    ) -> None:
        self.sample_rate = sample_rate
        self.silence_ms = silence_ms
        self.threshold = threshold
        self.device = device or None  # None = system default input
        self.max_seconds = max_seconds  # hard cap so a silent/wrong device can't hang
        self.onset_timeout = onset_timeout  # give up if no speech starts in this long
        self.min_speech_ms = min_speech_ms  # reject blips: need this much real speech

    async def record_utterance(self, on_level=None) -> Utterance | None:  # pragma: no cover
        import numpy as np

        # Resolve a saved device name to an index (opening by full name is flaky).
        dev = _resolve_device(self.device, want_output=False)
        silence_blocks = max(1, self.silence_ms // 30)
        captured: list[bytes] = []
        trailing_silence = 0
        heard_speech = False
        speech_blocks = 0  # how many blocks actually crossed the speech threshold
        loop = asyncio.get_running_loop()

        # Callback-mode capture (safe teardown on Ctrl-C). Prefer 16 kHz (what STT
        # wants); a raw hw device that rejects it falls back to its native rate,
        # resampled afterwards. 30 ms blocks for VAD granularity.
        stream, frames, capture_sr, block = _open_capture(dev, self.sample_rate, 30)

        max_blocks = max(1, int(self.max_seconds * capture_sr / block))
        onset_blocks = max(1, int(self.onset_timeout * capture_sr / block))
        min_speech_blocks = max(1, int(self.min_speech_ms / 1000 * capture_sr / block))
        calib_blocks = 8                  # ~240 ms to measure the noise floor
        noise: list[float] = []
        threshold = self.threshold        # refined from the noise floor below
        try:
            n = 0
            while n < max_blocks:
                data = await _next_frame(loop, frames)
                if data is None:
                    continue  # mic stall (~1 s) — keep waiting, don't count it
                captured.append(data)
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0

                if not heard_speech and n < calib_blocks:
                    noise.append(rms)
                    if n == calib_blocks - 1:  # adapt to the mic: floor + noise-relative
                        threshold = max(sum(noise) / len(noise) * 3.0, 0.008)

                # Nobody started talking within onset_timeout -> stop, don't camp on
                # the mic for the full max_seconds.
                if not heard_speech and n >= onset_blocks:
                    break

                if rms >= threshold:
                    heard_speech = True
                    speech_blocks += 1
                    trailing_silence = 0
                elif heard_speech:
                    trailing_silence += 1
                state = ("ending" if trailing_silence else "speaking") if heard_speech else "waiting"
                if on_level is not None:
                    on_level(rms, state)
                if heard_speech and trailing_silence >= silence_blocks:
                    break
                n += 1
        finally:
            _close_capture(stream)

        # Reject silence and brief blips (a click/breath that tripped the threshold
        # for a moment): Whisper hallucinates whole sentences from such clips.
        if not heard_speech or speech_blocks < min_speech_blocks:
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
