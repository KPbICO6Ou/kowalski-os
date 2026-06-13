"""Vision-LLM backends: turn a screenshot (PNG bytes) + prompt into a
textual description. Production uses a vision model (qwen2.5-vl / llava)
served by Ollama; a mock backend returns canned text for tests.
"""

from __future__ import annotations

import base64
from typing import Protocol, runtime_checkable


@runtime_checkable
class VisionModel(Protocol):
    async def describe(self, png: bytes, prompt: str) -> str:
        """Describe the PNG image given the prompt; return the model's text."""
        ...


class OllamaVisionModel:
    """Describe an image via an Ollama-served vision model (e.g. qwen2.5vl, llava).

    `import ollama` happens lazily so the dependency is only required when the
    model is actually used.
    """

    def __init__(self, host: str, model: str = "qwen2.5vl"):
        self.host = host
        self.model = model

    async def describe(self, png: bytes, prompt: str) -> str:
        import ollama

        client = ollama.AsyncClient(host=self.host)
        b64png = base64.b64encode(png).decode("ascii")
        response = await client.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt, "images": [b64png]}],
        )
        message = response.get("message", {}) if isinstance(response, dict) else response.message
        content = (
            message.get("content", "") if isinstance(message, dict) else (message.content or "")
        )
        return content.strip()


class MockVisionModel:
    """Test double: returns a canned reply and records what it was asked."""

    def __init__(self, reply: str = "A desktop with a code editor and a terminal."):
        self.reply = reply
        self.last_prompt: str | None = None
        self.last_png: bytes | None = None
        self.received_image = False
        self.calls = 0

    async def describe(self, png: bytes, prompt: str) -> str:
        self.calls += 1
        self.last_prompt = prompt
        self.last_png = png
        self.received_image = bool(png)
        return self.reply
