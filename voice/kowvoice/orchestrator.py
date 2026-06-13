"""The voice pipeline as a pure asyncio state machine.

Sequence per turn:
    IDLE  --wake-->  LISTENING --VAD endpoint--> TRANSCRIBING --STT-->
    THINKING --agent stream--> SPEAKING (TTS per sentence) --> IDLE

Barge-in: while the agent is speaking, a concurrent monitor watches the mic; if
the user starts talking, playback and the answer stream are cancelled and the
turn loops back to LISTENING to capture the new utterance.

This module imports only protocols, types, and the segmenter — never httpx,
sounddevice, or any model — so the whole control flow is testable with mocks on
any OS."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from .protocols import (
    AgentSession,
    AudioSink,
    Interrupter,
    Recorder,
    SttClient,
    TtsClient,
    WakeListener,
)
from .segmenter import SentenceSegmenter
from .settings import VoiceSettings
from .types import VoiceEvent, VoiceState

log = logging.getLogger(__name__)

EventSink = Callable[[VoiceEvent], None]


class VoiceOrchestrator:
    def __init__(
        self,
        *,
        wake: WakeListener,
        recorder: Recorder,
        stt: SttClient,
        agent: AgentSession,
        tts: TtsClient,
        sink: AudioSink,
        interrupter: Interrupter,
        settings: VoiceSettings,
        on_event: EventSink | None = None,
    ) -> None:
        self.wake = wake
        self.recorder = recorder
        self.stt = stt
        self.agent = agent
        self.tts = tts
        self.sink = sink
        self.interrupter = interrupter
        self.settings = settings
        self.on_event = on_event
        self._state = VoiceState.IDLE
        self._stop = asyncio.Event()

    # -- public API -----------------------------------------------------------

    @property
    def state(self) -> VoiceState:
        return self._state

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        """Loop wake->turn cycles until stop() is called."""
        self._emit("ready", state=VoiceState.IDLE)
        while not self._stop.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # one failed turn must not kill the loop
                log.exception("voice turn failed")
                self._emit("error", text=str(exc))

    async def run_once(self) -> None:
        """One full wake -> answer cycle (used by `kow-voice demo` and tests)."""
        self._emit("state", state=VoiceState.IDLE)
        await self.wake.wait_for_wake()
        if self._stop.is_set():
            return
        await self._handle_turn()
        self._emit("state", state=VoiceState.IDLE)

    # -- internals ------------------------------------------------------------

    async def _handle_turn(self) -> None:
        while True:
            self._emit("state", state=VoiceState.LISTENING)
            utterance = await self.recorder.record_utterance()
            if utterance is None or utterance.is_empty:
                self._emit("no_speech", state=VoiceState.IDLE)
                return

            self._emit("state", state=VoiceState.TRANSCRIBING)
            transcript = await self.stt.transcribe(
                utterance, language=self.settings.stt_language or None
            )
            if not transcript.text.strip():
                self._emit("no_speech", state=VoiceState.IDLE)
                return
            self._emit("transcript", state=VoiceState.TRANSCRIBING, text=transcript.text)

            barged = await self._respond(transcript.text)
            if barged:
                continue  # user interrupted -> capture the new utterance
            return

    async def _respond(self, text: str) -> bool:
        """Stream the answer and speak it. Returns True if the user barged in."""
        if not self.settings.barge_in:
            await self._stream_and_speak(text)
            return False

        speak_task = asyncio.create_task(self._stream_and_speak(text))
        barge_task = asyncio.create_task(self.interrupter.wait_for_barge_in())
        done, _ = await asyncio.wait(
            {speak_task, barge_task}, return_when=asyncio.FIRST_COMPLETED
        )

        if barge_task in done and not barge_task.cancelled():
            speak_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await speak_task
            await self.sink.stop()
            self._emit("barge_in", state=VoiceState.LISTENING)
            return True

        barge_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await barge_task
        return False

    async def _stream_and_speak(self, text: str) -> None:
        segmenter = SentenceSegmenter()
        spoken_anything = False
        answer_parts: list[str] = []
        self._emit("state", state=VoiceState.THINKING)

        async for delta in self.agent.ask(text):
            answer_parts.append(delta)
            for sentence in segmenter.feed(delta):
                spoken_anything = self._enter_speaking(spoken_anything)
                await self._speak_sentence(sentence)

        tail = segmenter.flush()
        if tail:
            self._enter_speaking(spoken_anything)
            await self._speak_sentence(tail)

        self._emit("answer", state=VoiceState.SPEAKING, text="".join(answer_parts).strip())

    def _enter_speaking(self, already: bool) -> bool:
        if not already:
            self._emit("state", state=VoiceState.SPEAKING)
        return True

    async def _speak_sentence(self, sentence: str) -> None:
        self._emit("speak", state=VoiceState.SPEAKING, text=sentence)
        clip = await self.tts.synthesize(sentence)
        await self.sink.play(clip)

    def _emit(self, kind: str, *, state: VoiceState | None = None, text: str | None = None) -> None:
        if state is not None:
            self._state = state
        if self.on_event is not None:
            self.on_event(VoiceEvent(kind=kind, state=self._state, text=text))
