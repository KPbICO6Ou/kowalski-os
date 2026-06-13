"""In-memory mail backend for development and tests. No network, no creds.
Bootstrap registers this by default so the mail capability exists in dev with
an honest empty inbox."""

from __future__ import annotations

import uuid

from .types import Draft, Message, MessageSummary

FOLDERS = ["INBOX", "Sent"]


class MockMailBackend:
    def __init__(self, seed: list[Message] | None = None):
        self.messages: dict[str, Message] = {m.id: m for m in (seed or [])}
        self.sent: list[Draft] = []

    async def search(
        self, query: str, folder: str = "INBOX", limit: int = 20
    ) -> list[MessageSummary]:
        needle = query.lower()
        results: list[MessageSummary] = []
        for message in self.messages.values():
            if message.folder != folder:
                continue
            haystack = f"{message.subject}\n{message.from_addr}\n{message.snippet}".lower()
            if needle in haystack:
                results.append(message.summary())
        return results[:limit]

    async def read(self, message_id: str) -> Message:
        if message_id not in self.messages:
            raise KeyError(f"no message with id {message_id}")
        return self.messages[message_id]

    async def list_folders(self) -> list[str]:
        return list(FOLDERS)

    async def send(self, draft: Draft) -> str:
        self.sent.append(draft)
        return f"mock-{uuid.uuid4().hex[:12]}"
