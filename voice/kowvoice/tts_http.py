"""HTTP TTS client for wachawo/text-to-speech (POST /api/tts).

The response body is the audio; inference time comes back in the `X-Elapsed`
header (see the planned text-to-speech PR) so latency can be split into network
vs synthesis."""

from __future__ import annotations

import re

from .types import AudioClip

TTS_LANGUAGE_RE = re.compile(r"^[a-z]{2}$")  # /api/tts validates an exactly-2-letter language


def tts_language(lang: str | None) -> str | None:
    """Normalize a language to what /api/tts accepts: exactly 2 letters; a locale
    like "en-US" -> "en". "auto" (STT-only) and 3-letter codes -> None, so we omit
    the field and let the server pick its default instead of 400-ing."""
    if not lang:
        return None
    primary = lang.strip().lower().split("-")[0]  # en-US -> en, auto -> auto
    return primary if TTS_LANGUAGE_RE.match(primary) else None


class HttpTtsClient:
    def __init__(
        self, url: str, token: str = "", engine: str = "", timeout: float = 30.0,
        language: str = "",
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.engine = engine  # kept for compat/health; not sent — the server picks the engine
        self.timeout = timeout
        self.language = language

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def synthesize(self, text: str) -> AudioClip:
        import httpx

        # wachawo/text-to-speech accepts {text, language?} and rejects unknown fields
        # (Marshmallow strict) — sending "format"/"engine" 400s; the server picks the
        # engine itself. `language` is honoured per-request (empty -> server default).
        body: dict = {"text": text}
        lang = tts_language(self.language)
        if lang:
            body["language"] = lang
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.url}/api/tts", headers=self._headers(), json=body)
            resp.raise_for_status()
            elapsed = resp.headers.get("X-Elapsed")
            return AudioClip(
                audio=resp.content,
                sample_rate=None,
                format="wav",
                elapsed_s=float(elapsed) if elapsed else None,
            )

    async def health(self) -> dict:
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.url}/api/health", headers=self._headers())
            resp.raise_for_status()
            return resp.json()
