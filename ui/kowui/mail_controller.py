"""Mail window controller: pure asyncio glue between the mail backend, the
kow-core daemon (AI actions), and a view.

No UI imports — views plug in via the MailCallbacks protocol, so everything here
is testable without GTK. Mailbox reads go straight to the shared backend (the
same one `kow mail` uses, per KOW_MAIL_BACKEND); AI actions stream through the
daemon (OmniClient.ask) so the LLM work stays in kow-core. Sending is
deterministic (backend.send after the view's explicit confirmation) — no LLM in
the send path."""

from __future__ import annotations

import uuid
from typing import Any, Protocol

BODY_TRIM = 4000
AI_DENIED_NOTE = "(tool call denied — the mail AI panel only reads; use kow chat for actions)"


class MailCallbacks(Protocol):
    """View-side hooks; every call happens on the controller's asyncio thread."""

    def on_folders(self, folders: list[str]) -> None: ...

    def on_messages(self, summaries: list[Any]) -> None: ...

    def on_message(self, message: Any) -> None: ...

    def on_ai_token(self, text: str) -> None: ...

    def on_ai_done(self) -> None: ...

    def on_sent(self, detail: str) -> None: ...

    def on_error(self, message: str) -> None: ...


def message_context(message) -> str:
    """The email as prompt context (headers + trimmed body)."""
    body = (message.body_text or "")[:BODY_TRIM]
    return (f"Subject: {message.subject}\nFrom: {message.from_addr}\n"
            f"Date: {message.date}\n\n{body}")


def summarize_prompt(message) -> str:
    return ("Summarize this email in 2-4 short bullet points, in the email's "
            "own language. Do not use any tools.\n\n" + message_context(message))


def reply_prompt(message) -> str:
    return ("Draft a polite reply to this email, in the email's own language. "
            "Output ONLY the reply body text — no subject line, no commentary, "
            "and do not use any tools.\n\n" + message_context(message))


def translate_prompt(message, target_language: str = "Russian") -> str:
    return (f"Translate this email into {target_language}. Output only the "
            "translation. Do not use any tools.\n\n" + message_context(message))


def question_prompt(message, question: str) -> str:
    return ("Answer the question about this email, in the question's language. "
            "Do not use any tools.\n\nQuestion: " + question.strip() + "\n\n"
            + message_context(message))


def reply_subject(subject: str) -> str:
    subject = (subject or "").strip()
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


class MailController:
    """Drives the mail backend + daemon asks and fans results out to a view.

    `client` (OmniClient) may be None — mailbox browsing still works and AI
    actions report a clear error. AI follow-ups about one message share a
    conversation, so "ask about this email" keeps context per message."""

    def __init__(self, backend, client, callbacks: MailCallbacks):
        self.backend = backend
        self.client = client
        self.callbacks = callbacks
        self.conversations: dict[str, str] = {}  # message id -> conversation id

    async def load_folders(self) -> None:
        try:
            self.callbacks.on_folders(await self.backend.list_folders())
        except Exception as exc:
            self.callbacks.on_error(f"folders: {exc}")

    async def search(self, query: str = "", folder: str = "INBOX", limit: int = 50) -> None:
        try:
            summaries = await self.backend.search(query, folder=folder, limit=limit)
        except Exception as exc:
            self.callbacks.on_error(f"search: {exc}")
            return
        self.callbacks.on_messages(summaries)

    async def open_message(self, message_id: str) -> None:
        try:
            message = await self.backend.read(message_id)
        except Exception as exc:
            self.callbacks.on_error(f"read: {exc}")
            return
        self.callbacks.on_message(message)

    async def summarize(self, message) -> None:
        await self.run_ai(message, summarize_prompt(message))

    async def draft_reply(self, message) -> None:
        await self.run_ai(message, reply_prompt(message))

    async def translate(self, message) -> None:
        await self.run_ai(message, translate_prompt(message))

    async def ask_about(self, message, question: str) -> None:
        await self.run_ai(message, question_prompt(message, question))

    async def run_ai(self, message, prompt: str) -> None:
        """Stream one daemon ask into the AI callbacks. The panel is read-only by
        design: a ConfirmRequestEvent is auto-denied with a note."""
        if self.client is None:
            self.callbacks.on_error("AI actions need the kow-core daemon (kow serve)")
            return
        conversation = self.conversations.setdefault(str(message.id), uuid.uuid4().hex)
        try:
            async for event in self.client.ask(prompt, conversation):
                kind = event.get("event")
                if kind == "TokenEvent":
                    self.callbacks.on_ai_token(event.get("text", ""))
                elif kind == "ConfirmRequestEvent":
                    await self.client.confirm(event.get("request_id", ""), False)
                    self.callbacks.on_ai_token(f"\n{AI_DENIED_NOTE}\n")
                elif kind == "DoneEvent":
                    self.callbacks.on_ai_done()
                elif kind == "ErrorEvent":
                    self.callbacks.on_error(event.get("message", ""))
        except Exception as exc:  # transport failures surface like ErrorEvent
            self.callbacks.on_error(str(exc))

    async def send_reply(self, message, body: str) -> None:
        """Send `body` as a reply to `message` (the view confirmed already)."""
        from kowalski.mail import Draft

        body = (body or "").strip()
        if not body:
            self.callbacks.on_error("empty reply — nothing to send")
            return
        draft = Draft(to=[message.from_addr], subject=reply_subject(message.subject), body=body)
        try:
            sent_id = await self.backend.send(draft)
        except Exception as exc:
            self.callbacks.on_error(f"send failed: {exc}")
            return
        self.callbacks.on_sent(f"sent to {message.from_addr} (id {sent_id})")
