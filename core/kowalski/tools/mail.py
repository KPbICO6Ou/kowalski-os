"""mail.* tools: search/read an inbox, compose an AI draft, and send.

Backend is pluggable (mock for dev/tests, IMAP/SMTP for real servers); drafts
are stored locally via DraftStore.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from ..mail.backend import MailBackend
from ..mail.drafts import DraftStore
from ..mail.types import Draft
from .base import RiskLevel, ToolDef, ToolResult

BODY_TRIM = 4000


class MailSearchArgs(BaseModel):
    query: str = Field(description="Substring matched against subject/from/snippet")
    folder: str = Field(default="INBOX")
    limit: int = Field(default=20, ge=1, le=100)


class MailReadArgs(BaseModel):
    message_id: str = Field(min_length=1)


class MailDraftArgs(BaseModel):
    to: list[str] = Field(min_length=1, description="Recipient addresses")
    subject: str
    body: str = Field(description="Message body composed by the agent (the AI draft)")
    cc: list[str] = Field(default_factory=list)
    in_reply_to: str | None = None


class MailSendArgs(BaseModel):
    """Send EITHER a stored draft (draft_id) OR an inline message
    (to+subject+body). Exactly one form is allowed."""

    draft_id: int | None = None
    to: list[str] | None = None
    subject: str | None = None
    body: str | None = None
    cc: list[str] = Field(default_factory=list)
    in_reply_to: str | None = None

    @model_validator(mode="after")
    def exactly_one_form(self) -> "MailSendArgs":
        has_draft = self.draft_id is not None
        has_inline = any(v is not None for v in (self.to, self.subject, self.body))
        if has_draft and has_inline:
            raise ValueError("provide either draft_id or inline to/subject/body, not both")
        if not has_draft and not has_inline:
            raise ValueError("provide either draft_id or inline to/subject/body")
        if has_inline and not (self.to and self.subject is not None and self.body is not None):
            raise ValueError("inline send requires all of to, subject, body")
        return self


def _format_summaries(summaries) -> str:
    if not summaries:
        return "No messages found."
    lines = []
    for s in summaries:
        flag = "* " if s.unread else "  "
        lines.append(f"{flag}[{s.id}] {s.date} — {s.from_addr}: {s.subject}")
    return f"{len(summaries)} messages:\n" + "\n".join(lines)


def build_tools(backend: MailBackend, draft_store: DraftStore) -> list[ToolDef]:
    async def mail_search(args: MailSearchArgs) -> ToolResult:
        summaries = await backend.search(args.query, folder=args.folder, limit=args.limit)
        data = [vars(s) for s in summaries]
        return ToolResult(ok=True, content=_format_summaries(summaries), data=data)

    async def mail_read(args: MailReadArgs) -> ToolResult:
        try:
            message = await backend.read(args.message_id)
        except (KeyError, LookupError) as exc:
            return ToolResult(ok=False, content=f"Message not found: {exc}")
        body = message.body_text
        if len(body) > BODY_TRIM:
            body = body[:BODY_TRIM] + "\n…(truncated)"
        header = (
            f"Subject: {message.subject}\n"
            f"From: {message.from_addr}\n"
            f"To: {', '.join(message.to)}\n"
            f"Date: {message.date}\n\n"
        )
        return ToolResult(ok=True, content=header + body, data=vars(message))

    async def mail_draft(args: MailDraftArgs) -> ToolResult:
        draft = Draft(
            to=args.to,
            subject=args.subject,
            body=args.body,
            cc=args.cc,
            in_reply_to=args.in_reply_to,
        )
        draft_id = draft_store.save(draft)
        return ToolResult(
            ok=True,
            content=f"Draft #{draft_id} saved to {', '.join(args.to)}: {args.subject}",
            data={"draft_id": draft_id},
        )

    async def mail_send(args: MailSendArgs) -> ToolResult:
        from_draft_id: int | None = None
        if args.draft_id is not None:
            draft = draft_store.get(args.draft_id)
            if draft is None:
                return ToolResult(ok=False, content=f"No draft with id {args.draft_id}.")
            from_draft_id = args.draft_id
        else:
            # validator guarantees to/subject/body are present here
            draft = Draft(
                to=args.to or [],
                subject=args.subject or "",
                body=args.body or "",
                cc=args.cc,
                in_reply_to=args.in_reply_to,
            )
        try:
            sent_id = await backend.send(draft)
        except Exception as exc:  # backend/transport failures must not crash the loop
            return ToolResult(ok=False, content=f"Send failed: {exc}")
        if from_draft_id is not None:
            draft_store.mark_sent(from_draft_id)
        return ToolResult(
            ok=True,
            content=f"Sent to {', '.join(draft.to)}: {draft.subject} (id {sent_id})",
            data={"sent_id": sent_id, "draft_id": from_draft_id},
        )

    return [
        ToolDef(
            name="mail.search",
            description=(
                "Search the mailbox by substring over subject/sender/snippet and "
                "return matching message summaries (id, date, sender, subject)."
            ),
            args_model=MailSearchArgs,
            risk=RiskLevel.READ,
            handler=mail_search,
        ),
        ToolDef(
            name="mail.read",
            description="Read one message by id, returning its headers and body text.",
            args_model=MailReadArgs,
            risk=RiskLevel.READ,
            handler=mail_read,
        ),
        ToolDef(
            name="mail.draft",
            description=(
                "Compose and save a local email draft (the AI writes the body). "
                "Returns a draft id you can later pass to mail.send."
            ),
            args_model=MailDraftArgs,
            risk=RiskLevel.WRITE,
            handler=mail_draft,
        ),
        ToolDef(
            name="mail.send",
            description=(
                "Send an email — either an existing draft (draft_id) or an inline "
                "message (to/subject/body). Always requires confirmation."
            ),
            args_model=MailSendArgs,
            # DESTRUCTIVE on purpose: an outbound send is irreversible — once the
            # message leaves it cannot be unsent. DESTRUCTIVE makes the policy
            # ALWAYS confirm and never auto-allow it (unlike NETWORK, which
            # KOW_AUTO_ALLOW_NETWORK can silence).
            risk=RiskLevel.DESTRUCTIVE,
            handler=mail_send,
        ),
    ]
