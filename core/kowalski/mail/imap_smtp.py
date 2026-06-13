"""Real IMAP (search/read/list) + SMTP (send) backend.

HONEST CAVEAT: this path needs a live mail server and valid credentials. It is
NOT exercised in CI — there is no test server. The mock backend is the tested
default; this is provided so a real deployment can flip KOW_MAIL_BACKEND=imap.

Third-party deps (imap_tools, aiosmtplib) are lazy-imported, matching how core
treats other optional deps (ollama/fastapi/dasbus): importing this module never
requires them; only calling the methods does.
"""

from __future__ import annotations

import asyncio
from email.message import EmailMessage

from ..config import Config
from .types import Draft, Message, MessageSummary


class ImapSmtpBackend:
    def __init__(self, config: Config):
        self._imap_host = config.get("IMAP_HOST")
        self._imap_port = config.get_int("IMAP_PORT")
        self._imap_user = config.get("IMAP_USER")
        self._imap_password = config.get("IMAP_PASSWORD")
        self._imap_ssl = config.get_bool("IMAP_SSL")
        self._smtp_host = config.get("SMTP_HOST")
        self._smtp_port = config.get_int("SMTP_PORT")
        self._smtp_user = config.get("SMTP_USER")
        self._smtp_password = config.get("SMTP_PASSWORD")
        self._smtp_tls = config.get_bool("SMTP_TLS")
        self._mail_from = config.get("MAIL_FROM") or self._smtp_user

    @staticmethod
    def importable() -> bool:
        """True if the optional deps are present. Bootstrap uses this to skip
        the mail tools rather than crash when KOW_MAIL_BACKEND=imap but the
        'mail' extra was never installed."""
        import importlib.util

        return all(
            importlib.util.find_spec(name) is not None
            for name in ("imap_tools", "aiosmtplib")
        )

    # --- IMAP: blocking imap_tools calls are pushed to a worker thread. ---

    def _mailbox(self):
        from imap_tools import MailBox, MailBoxUnencrypted

        cls = MailBox if self._imap_ssl else MailBoxUnencrypted
        return cls(self._imap_host, port=self._imap_port).login(
            self._imap_user, self._imap_password
        )

    def _search_sync(self, query: str, folder: str, limit: int) -> list[MessageSummary]:
        from imap_tools import AND

        criteria = AND(text=query) if query else AND(all=True)
        out: list[MessageSummary] = []
        with self._mailbox() as box:
            box.folder.set(folder)
            for msg in box.fetch(criteria, limit=limit, reverse=True, mark_seen=False):
                out.append(
                    MessageSummary(
                        id=str(msg.uid),
                        folder=folder,
                        from_addr=msg.from_,
                        to=list(msg.to),
                        subject=msg.subject,
                        date=msg.date_str,
                        snippet=(msg.text or "")[:200],
                        unread="\\Seen" not in msg.flags,
                    )
                )
        return out

    def _read_sync(self, message_id: str) -> Message:
        from imap_tools import AND

        with self._mailbox() as box:
            for msg in box.fetch(AND(uid=message_id), limit=1, mark_seen=False):
                return Message(
                    id=str(msg.uid),
                    folder=box.folder.get(),
                    from_addr=msg.from_,
                    to=list(msg.to),
                    subject=msg.subject,
                    date=msg.date_str,
                    snippet=(msg.text or "")[:200],
                    unread="\\Seen" not in msg.flags,
                    body_text=msg.text or "",
                    body_html=msg.html or None,
                )
        raise KeyError(f"no message with id {message_id}")

    def _list_folders_sync(self) -> list[str]:
        with self._mailbox() as box:
            return [f.name for f in box.folder.list()]

    async def search(
        self, query: str, folder: str = "INBOX", limit: int = 20
    ) -> list[MessageSummary]:
        return await asyncio.to_thread(self._search_sync, query, folder, limit)

    async def read(self, message_id: str) -> Message:
        return await asyncio.to_thread(self._read_sync, message_id)

    async def list_folders(self) -> list[str]:
        return await asyncio.to_thread(self._list_folders_sync)

    async def send(self, draft: Draft) -> str:
        import aiosmtplib

        message = EmailMessage()
        message["From"] = self._mail_from
        message["To"] = ", ".join(draft.to)
        if draft.cc:
            message["Cc"] = ", ".join(draft.cc)
        message["Subject"] = draft.subject
        if draft.in_reply_to:
            message["In-Reply-To"] = draft.in_reply_to
        message.set_content(draft.body)

        recipients = [*draft.to, *draft.cc]
        result = await aiosmtplib.send(
            message,
            hostname=self._smtp_host,
            port=self._smtp_port,
            username=self._smtp_user or None,
            password=self._smtp_password or None,
            start_tls=self._smtp_tls,
            recipients=recipients,
        )
        # aiosmtplib.send returns (errors_dict, response_str)
        return str(result[1]) if isinstance(result, tuple) else "sent"
