"""ContextProvider: produces extra system-prompt text from the user profile and
the long-term memories most relevant to the current prompt.

The integrator appends the returned fragment to the static system prompt.
"""

from __future__ import annotations

from typing import Protocol

from .embedder import Embedder
from .store import MemoryStore


class ContextProvider(Protocol):
    async def context_for(self, prompt: str) -> str: ...


class MemoryContextProvider:
    """Combines all profile facts with the top-k memories relevant to `prompt`.

    Resilient by design: if the embedder fails (e.g. Ollama is down), it falls
    back to a profile-only fragment and never raises. Returns "" when there are
    neither facts nor relevant memories.
    """

    def __init__(self, store: MemoryStore, embedder: Embedder, k: int = 5):
        self.store = store
        self.embedder = embedder
        self.k = k

    async def context_for(self, prompt: str) -> str:
        facts = self.store.all_facts()

        memories: list[dict] = []
        try:
            query_embedding = await self.embedder.embed(prompt)
            hits = self.store.recall(query_embedding, self.k)
            memories = [h for h in hits if h["score"] > 0.0]
        except Exception:
            # Embedder unavailable: degrade gracefully to profile-only context.
            memories = []

        sections: list[str] = []
        if facts:
            lines = [f"- {key}: {value}" for key, value in facts.items()]
            sections.append("Known facts about the user:\n" + "\n".join(lines))
        if memories:
            lines = [f"- {m['text']}" for m in memories]
            sections.append("Relevant long-term memories:\n" + "\n".join(lines))

        return "\n\n".join(sections)
