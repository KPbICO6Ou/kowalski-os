"""HTTP STT client for wachawo/speech-to-text (POST /api/stt).

Sends the captured utterance as a WAV upload; reads back {text, elapsed}. The
optional `language` field rides along (see the planned speech-to-text PR); the
server falls back to its own WHISPER_LANGUAGE when it is omitted."""

from __future__ import annotations

import io
import wave

from .types import Transcript, Utterance


def pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # PCM16
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


class HttpSttClient:
    def __init__(self, url: str, token: str = "", timeout: float = 30.0) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def transcribe(self, utterance: Utterance, language: str | None = None) -> Transcript:
        import httpx

        wav = pcm_to_wav(utterance.pcm, utterance.sample_rate)
        data = {"language": language} if language else {}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.url}/api/stt",
                headers=self._headers(),
                files={"file": ("audio.wav", wav, "audio/wav")},
                data=data,
            )
            resp.raise_for_status()
            payload = resp.json()
        return Transcript(
            text=payload.get("text", ""),
            language=payload.get("language") or language,
            elapsed_s=payload.get("elapsed"),
        )

    async def health(self) -> dict:
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.url}/api/health", headers=self._headers())
            resp.raise_for_status()
            return resp.json()
