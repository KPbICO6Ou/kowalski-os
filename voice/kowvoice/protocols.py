"""Seams between the (pure, testable) orchestrator and the hardware/network world.

Each protocol has a mocked implementation in `mocks.py` (used for development and
tests on any OS) and a real adapter (`stt_http`, `tts_http`, `agent_socket`,
`audio_devices`) that needs a microphone, the STT/TTS HTTP services, or a running
kow-core daemon."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from .types import AudioClip, Transcript, Utterance


@runtime_checkable
class WakeListener(Protocol):
    async def wait_for_wake(self) -> None:
        """Return when the wake word is detected (one trigger per call)."""


@runtime_checkable
class Recorder(Protocol):
    async def record_utterance(self, on_level=None) -> Utterance | None:
        """Capture speech until the VAD endpoint; None on silence/timeout.
        on_level(rms, state) is called per audio block for a live level meter."""


@runtime_checkable
class Interrupter(Protocol):
    async def wait_for_barge_in(self) -> None:
        """Return when the user starts speaking while the agent is talking.

        A fresh call re-arms the monitor for the next speaking phase."""


@runtime_checkable
class SttClient(Protocol):
    async def transcribe(self, utterance: Utterance, language: str | None = None) -> Transcript: ...


@runtime_checkable
class TtsClient(Protocol):
    async def synthesize(self, text: str) -> AudioClip: ...


@runtime_checkable
class AudioSink(Protocol):
    async def play(self, clip: AudioClip) -> None: ...
    async def stop(self) -> None:
        """Interrupt playback immediately (barge-in)."""


@runtime_checkable
class AgentSession(Protocol):
    def ask(self, text: str) -> AsyncIterator[str]:
        """Stream the agent's answer as text deltas for the given user turn."""
