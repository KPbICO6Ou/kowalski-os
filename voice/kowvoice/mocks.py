"""Scripted, in-process implementations of every voice seam.

These let the whole pipeline run and be tested on any OS without a microphone,
the STT/TTS services, or a kow-core daemon. `kow-voice demo` wires them up."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

from .types import AudioClip, Transcript, Utterance


class MockWakeListener:
    """Fires `fires` times, then blocks forever (until the task is cancelled)."""

    def __init__(self, fires: int = 1) -> None:
        self._remaining = fires

    async def wait_for_wake(self) -> None:
        if self._remaining > 0:
            self._remaining -= 1
            return
        await asyncio.Event().wait()


class MockRecorder:
    """Returns each scripted utterance in turn; None when the script runs out."""

    def __init__(self, utterances: list[Utterance]) -> None:
        self._queue = list(utterances)
        self.calls = 0

    async def record_utterance(self, on_level=None) -> Utterance | None:
        self.calls += 1
        return self._queue.pop(0) if self._queue else None


class MockSttClient:
    def __init__(self, transcripts: list[str]) -> None:
        self._queue = list(transcripts)
        self.calls: list[Utterance] = []

    async def transcribe(self, utterance: Utterance, language: str | None = None) -> Transcript:
        self.calls.append(utterance)
        text = self._queue.pop(0) if self._queue else ""
        return Transcript(text=text, language=language, elapsed_s=0.05)


class MockAgentSession:
    """Yields the same scripted answer deltas for every turn."""

    def __init__(self, deltas: list[str]) -> None:
        self._deltas = list(deltas)
        self.asked: list[str] = []

    async def ask(self, text: str) -> AsyncIterator[str]:
        self.asked.append(text)
        for delta in self._deltas:
            await asyncio.sleep(0)
            yield delta


class MockTtsClient:
    """Returns synthetic PCM sized to the text; optional hook fires per call
    (used to trigger a deterministic barge-in mid-answer in tests)."""

    def __init__(self, on_synthesize: Callable[[str, int], None] | None = None) -> None:
        self.calls: list[str] = []
        self._on_synthesize = on_synthesize

    async def synthesize(self, text: str) -> AudioClip:
        self.calls.append(text)
        if self._on_synthesize is not None:
            self._on_synthesize(text, len(self.calls))
        return AudioClip(audio=b"\x00\x00" * max(1, len(text)), sample_rate=16000, format="pcm")


class MockAudioSink:
    def __init__(self, play_seconds: float = 0.02) -> None:
        self.played: list[AudioClip] = []
        self.stopped = False
        self._play_seconds = play_seconds

    async def play(self, clip: AudioClip) -> None:
        await asyncio.sleep(self._play_seconds)  # cancellable: barge-in interrupts here
        self.played.append(clip)

    async def stop(self) -> None:
        self.stopped = True


class MockInterrupter:
    """Re-arms a fresh event on each call; `trigger()` fires the current wait."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self.waits = 0

    async def wait_for_barge_in(self) -> None:
        self.waits += 1
        self._event = asyncio.Event()
        await self._event.wait()

    def trigger(self) -> None:
        self._event.set()


def silent_utterance(sample_rate: int = 16000, ms: int = 500) -> Utterance:
    return Utterance(pcm=b"\x00\x00" * (sample_rate * ms // 1000), sample_rate=sample_rate)
