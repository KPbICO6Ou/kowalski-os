"""Embedding backends: the Embedder protocol and the Ollama implementation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

BATCH_SIZE = 16


@runtime_checkable
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    """Embeds text batches with an Ollama embedding model (default nomic-embed-text)."""

    def __init__(self, host: str, model: str, batch_size: int = BATCH_SIZE):
        self.host = host
        self.model = model
        self.batch_size = batch_size
        self._client = None

    def _get_client(self):
        if self._client is None:
            import ollama

            self._client = ollama.Client(host=self.host)
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        import ollama

        client = self._get_client()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            try:
                response = client.embed(model=self.model, input=batch)
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
            vectors.extend([list(vector) for vector in response["embeddings"]])
        return vectors
