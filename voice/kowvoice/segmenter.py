"""Stream-friendly sentence segmentation: turn a token stream into whole
sentences so TTS can start speaking the first sentence while the rest is still
being generated (plan: 'TTS by sentences')."""

from __future__ import annotations

import re

# A sentence ends at terminal punctuation FOLLOWED by whitespace, or at a
# newline. End-of-buffer is deliberately not a boundary (more text may stream
# in); the final, unterminated sentence comes out via flush().
_BOUNDARY = re.compile(r"(.+?[.!?…]+(?=\s)|.+?\n)", re.DOTALL)


class SentenceSegmenter:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        """Append streamed text; return any newly completed sentences."""
        self._buffer += text
        sentences: list[str] = []
        while True:
            match = _BOUNDARY.match(self._buffer)
            if not match:
                break
            chunk = match.group(0)
            stripped = chunk.strip()
            if stripped:
                sentences.append(stripped)
            self._buffer = self._buffer[match.end():]
        return sentences

    def flush(self) -> str:
        """Return whatever text remains (the last, unterminated sentence)."""
        tail = self._buffer.strip()
        self._buffer = ""
        return tail
