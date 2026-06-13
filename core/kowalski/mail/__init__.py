"""Mail subsystem: typed message/draft models, a mockable backend Protocol,
an in-memory mock for dev/tests, an IMAP/SMTP backend for real servers, and a
SQLite-backed local DraftStore. Exposed to the agent via tools/mail.py."""

from __future__ import annotations

from .backend import MailBackend
from .drafts import DraftStore
from .mock import MockMailBackend
from .types import Draft, Message, MessageSummary

__all__ = [
    "Draft",
    "DraftStore",
    "MailBackend",
    "Message",
    "MessageSummary",
    "MockMailBackend",
]
