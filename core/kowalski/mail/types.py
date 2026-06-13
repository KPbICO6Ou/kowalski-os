"""Plain dataclasses for mail. Kept free of pydantic so backends and the store
can build them cheaply; the tool layer owns the pydantic arg models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MessageSummary:
    id: str
    folder: str
    from_addr: str
    to: list[str]
    subject: str
    date: str
    snippet: str
    unread: bool


@dataclass
class Message:
    id: str
    folder: str
    from_addr: str
    to: list[str]
    subject: str
    date: str
    snippet: str
    unread: bool
    body_text: str
    body_html: str | None = None

    def summary(self) -> MessageSummary:
        return MessageSummary(
            id=self.id,
            folder=self.folder,
            from_addr=self.from_addr,
            to=self.to,
            subject=self.subject,
            date=self.date,
            snippet=self.snippet,
            unread=self.unread,
        )


@dataclass
class Draft:
    to: list[str]
    subject: str
    body: str
    cc: list[str] = field(default_factory=list)
    in_reply_to: str | None = None
