"""HTTP TTS client for wachawo/text-to-speech (POST /api/tts).

The response body is the audio; inference time comes back in the `X-Elapsed`
header (see the planned text-to-speech PR) so latency can be split into network
vs synthesis."""

from __future__ import annotations

from .types import AudioClip


class HttpTtsClient:
    def __init__(
        self, url: str, token: str = "", engine: str = "", timeout: float = 30.0
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.engine = engine
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def synthesize(self, text: str) -> AudioClip:
        import httpx

        body: dict = {"text": text, "format": "wav"}
        if self.engine:
            body["engine"] = self.engine
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
