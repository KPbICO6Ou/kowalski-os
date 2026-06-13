"""Value types and events for the voice pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class VoiceState(StrEnum):
    IDLE = "idle"            # waiting for the wake word
    LISTENING = "listening"  # capturing the user's utterance (until VAD endpoint)
    TRANSCRIBING = "transcribing"  # utterance -> STT
    THINKING = "thinking"    # transcript -> agent, streaming the answer
    SPEAKING = "speaking"    # synthesizing + playing the answer


@dataclass
class Utterance:
    """A captured microphone utterance as raw little-endian PCM16."""

    pcm: bytes
    sample_rate: int = 16000

    @property
    def is_empty(self) -> bool:
        return len(self.pcm) == 0

    @property
    def duration_s(self) -> float:
        return len(self.pcm) / 2 / self.sample_rate if self.sample_rate else 0.0


@dataclass
class Transcript:
    text: str
    language: str | None = None
    elapsed_s: float | None = None  # server-side inference time (network vs inference split)


@dataclass
class AudioClip:
    """Synthesized audio. `format` distinguishes raw PCM from a WAV/MP3 container."""

    audio: bytes
    sample_rate: int | None = None
    format: str = "wav"  # "pcm" | "wav" | "mp3"
    elapsed_s: float | None = None


@dataclass
class VoiceEvent:
    """Emitted on every state change and notable moment, for a HUD/indicator."""

    kind: str          # state | ready | transcript | speak | answer | barge_in | no_speech | error
    state: VoiceState
    text: str | None = None
    detail: dict[str, Any] | None = None
