"""Mail subsystem: typed message/draft models, a mockable backend Protocol,
an in-memory mock for dev/tests, an IMAP/SMTP backend for real servers, and a
SQLite-backed local DraftStore. Exposed to the agent via tools/mail.py."""

from __future__ import annotations

from .backend import MailBackend
from .drafts import DraftStore
from .mock import MockMailBackend
from .types import Draft, Message, MessageSummary


def build_backend(config) -> MailBackend | None:
    """Build the mail backend per KOW_MAIL_BACKEND: "imap" (real IMAP/SMTP — needs
    the 'mail' extra; None when it isn't importable) or "mock" (in-memory dev
    default). Shared by the daemon (bootstrap) and the `kow mail` CLI."""
    kind = (config.get("KOW_MAIL_BACKEND", "mock") or "mock").lower()
    if kind == "imap":
        from .imap_smtp import ImapSmtpBackend

        if not ImapSmtpBackend.importable():
            return None
        return ImapSmtpBackend(config)
    return MockMailBackend()


__all__ = [
    "Draft",
    "DraftStore",
    "MailBackend",
    "Message",
    "MessageSummary",
    "MockMailBackend",
    "build_backend",
]
