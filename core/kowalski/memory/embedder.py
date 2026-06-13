"""Embedding backends for long-term memory: the Embedder protocol, the Ollama
implementation, and a deterministic mock used by the tests (no network)."""

from __future__ import annotations

import math
from typing import Protocol, runtime_checkable

DEFAULT_MODEL = "nomic-embed-text"


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class OllamaEmbedder:
    """Embeds a single text with an Ollama embedding model (default nomic-embed-text).

    The ollama client is imported lazily so the dependency is only required when
    this backend is actually used.
    """

    def __init__(self, host: str, model: str = DEFAULT_MODEL):
        self.host = host
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            import ollama

            self._client = ollama.AsyncClient(host=self.host)
        return self._client

    async def embed(self, text: str) -> list[float]:
        import ollama

        client = self._get_client()
        try:
            response = await client.embed(model=self.model, input=text)
        except ollama.ResponseError as exc:
            if "not found" in str(exc).lower():
                raise RuntimeError(
                    f"embedding model '{self.model}' is not available on {self.host}; "
                    f"run: ollama pull {self.model}"
                ) from exc
            raise RuntimeError(f"Ollama embed failed: {exc}") from exc
        except ConnectionError as exc:
            raise RuntimeError(
                f"cannot reach Ollama at {self.host}; is the server running?"
            ) from exc
        # ollama.embed returns {"embeddings": [[...]]} for a single input
        embeddings = response["embeddings"]
        return [float(x) for x in embeddings[0]]


# A tiny fixed vocabulary so similar texts land on overlapping dimensions. This
# keeps cosine similarity meaningful in tests without any external model.
_VOCAB: tuple[str, ...] = (
    "python",
    "coffee",
    "music",
    "dog",
    "cat",
    "travel",
    "food",
    "work",
    "family",
    "sport",
    "book",
    "movie",
    "weather",
    "city",
    "name",
    "color",
)


class MockEmbedder:
    """Deterministic, dependency-free embedder for tests.

    Builds a normalized vector over a fixed keyword vocabulary by counting word
    occurrences. Texts that share keywords get high cosine similarity; unrelated
    texts get low similarity. Dimension equals len(_VOCAB) (~16).
    """

    def __init__(self, vocab: tuple[str, ...] = _VOCAB):
        self.vocab = vocab
        self.dim = len(vocab)

    async def embed(self, text: str) -> list[float]:
        tokens = _tokenize(text)
        vec = [0.0] * self.dim
        for i, word in enumerate(self.vocab):
            vec[i] = float(tokens.count(word))
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]


def _tokenize(text: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return cleaned.split()
