"""Long-term memory and user personalization (plan module M8).

Provides:
- Embedder backends (Ollama + a deterministic Mock for tests).
- MemoryStore: semantic memories and a key/value user profile over the core Store.
- MemoryContextProvider: builds an extra system-prompt fragment from profile facts
  and the top-k memories relevant to the current prompt.
"""

from __future__ import annotations

from .context import ContextProvider, MemoryContextProvider
from .embedder import Embedder, MockEmbedder, OllamaEmbedder
from .store import MemoryStore

__all__ = [
    "ContextProvider",
    "Embedder",
    "MemoryContextProvider",
    "MemoryStore",
    "MockEmbedder",
    "OllamaEmbedder",
]
