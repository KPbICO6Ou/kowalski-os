"""VoiceChatIO: the mic→STT input and TTS→speaker output used by the chat loop.

Constructing it is cheap (no audio libs touched); sounddevice is only imported
when recording/playing, so the object is usable in TTS-only setups and fails
gracefully (caught by the caller) when the [mic] extra is absent."""

from __future__ import annotations


class VoiceChatIO:
    def __init__(self, settings):
        from .audio_devices import EnergyVadRecorder, SoundDeviceSink
        from .stt_http import HttpSttClient
        from .tts_http import HttpTtsClient

        self.settings = settings
        self.recorder = EnergyVadRecorder(
            settings.sample_rate, settings.vad_silence_ms, device=settings.input_device,
            onset_timeout=settings.no_speech_ms / 1000.0,
        )
        self.stt = HttpSttClient(settings.stt_url, settings.stt_token)
        self.tts = HttpTtsClient(settings.tts_url, settings.tts_token,
                                 language=settings.tts_language)
        self.sink = SoundDeviceSink(device=settings.output_device)

    async def record(self, on_level=None):
        """Capture one utterance from the mic (ends on trailing silence)."""
        return await self.recorder.record_utterance(on_level=on_level)

    async def transcribe(self, utterance) -> str | None:
        """Send a recorded utterance to STT; returns the text, or None when empty
        or a known Whisper silence-hallucination ('Спасибо за просмотр', etc.)."""
        from .stt_http import looks_like_hallucination

        if utterance is None or utterance.is_empty:
            return None
        transcript = await self.stt.transcribe(
            utterance, language=self.settings.stt_language or None
        )
        text = (transcript.text or "").strip()
        if not text or looks_like_hallucination(text):
            return None
        return text

    async def record_and_transcribe(self, on_level=None) -> str | None:
        return await self.transcribe(await self.record(on_level=on_level))

    async def play_cue(self) -> None:
        """Play the 'listening' earcon on the output device (best-effort)."""
        from .cues import play_listen_cue

        await play_listen_cue(self.sink, self.settings)

    async def speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        clip = await self.tts.synthesize(text)
        await self.sink.play(clip)
