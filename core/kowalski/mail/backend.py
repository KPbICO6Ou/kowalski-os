"""MailBackend Protocol: the seam between the agent tools and a concrete mail
transport. MockMailBackend and ImapSmtpBackend both satisfy it. Drafts are a
local concept (DraftStore), so they are deliberately absent from this Protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import Draft, Message, MessageSummary


@runtime_checkable
class MailBackend(Protocol):
    async def search(
        self, query: str, folder: str = "INBOX", limit: int = 20
    ) -> list[MessageSummary]:
        """Case-insensitive search; empty query lists the folder (up to limit)."""
        ...

    async def read(self, message_id: str) -> Message:
        """Fetch one message by id. Raises KeyError/LookupError if absent."""
        ...

    async def list_folders(self) -> list[str]:
        """Available mailbox folders, e.g. ['INBOX', 'Sent']."""
        ...

    async def send(self, draft: Draft) -> str:
        """Send a message; returns a sent-message id / confirmation string."""
        ...
