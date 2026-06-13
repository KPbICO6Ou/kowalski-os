import pytest
from pydantic import ValidationError

from kowalski.mail.drafts import DraftStore
from kowalski.mail.mock import MockMailBackend
from kowalski.mail.types import Draft, Message
from kowalski.tools.mail import MailSendArgs, build_tools


def seed_messages() -> list[Message]:
    return [
        Message(
            id="1", folder="INBOX", from_addr="alice@example.com",
            to=["me@example.com"], subject="Lunch on Friday?",
            date="2026-06-10", snippet="Want to grab lunch?",
            unread=True, body_text="Hi, want to grab lunch on Friday at noon?",
        ),
        Message(
            id="2", folder="INBOX", from_addr="bob@work.com",
            to=["me@example.com"], subject="Q2 budget review",
            date="2026-06-11", snippet="The numbers are ready",
            unread=False, body_text="The Q2 numbers are ready for your review.",
        ),
        Message(
            id="3", folder="INBOX", from_addr="newsletter@news.com",
            to=["me@example.com"], subject="Weekly digest",
            date="2026-06-12", snippet="Top stories this week",
            unread=True, body_text="Here are the top stories this week.",
        ),
    ]


def tool(backend, drafts, name: str):
    return next(t for t in build_tools(backend, drafts) if t.name == name)


@pytest.fixture
def backend() -> MockMailBackend:
    return MockMailBackend(seed=seed_messages())


@pytest.fixture
def drafts(tmp_store) -> DraftStore:
    return DraftStore(tmp_store)


class _AlwaysConfirm:
    """A human who approves everything, including DESTRUCTIVE. AutoConfirm no
    longer does this (it refuses DESTRUCTIVE/dangerous), so the send tests that
    want to exercise the post-confirmation path use this instead."""

    async def confirm(self, request) -> bool:
        return True


@pytest.fixture
def confirm_registry(policy, journal):
    from kowalski.tools.registry import ToolRegistry

    return ToolRegistry(
        policy=policy, journal=journal, confirmer=_AlwaysConfirm(), tool_timeout=5.0
    )


async def test_search_substring_and_format(backend, drafts):
    t = tool(backend, drafts, "mail.search")
    args = t.args_model(query="budget")
    result = await t.handler(args)
    assert result.ok
    assert len(result.data) == 1
    assert result.data[0]["id"] == "2"
    assert "Q2 budget review" in result.content
    assert "bob@work.com" in result.content


async def test_search_case_insensitive(backend, drafts):
    t = tool(backend, drafts, "mail.search")
    result = await t.handler(t.args_model(query="LUNCH"))
    assert [m["id"] for m in result.data] == ["1"]


async def test_search_empty_matches_all(backend, drafts):
    t = tool(backend, drafts, "mail.search")
    result = await t.handler(t.args_model(query=""))
    assert {m["id"] for m in result.data} == {"1", "2", "3"}


async def test_read_returns_body(backend, drafts):
    t = tool(backend, drafts, "mail.read")
    result = await t.handler(t.args_model(message_id="1"))
    assert result.ok
    assert "Subject: Lunch on Friday?" in result.content
    assert "From: alice@example.com" in result.content
    assert "want to grab lunch on Friday" in result.content
    assert result.data["body_text"]


async def test_read_missing(backend, drafts):
    t = tool(backend, drafts, "mail.read")
    result = await t.handler(t.args_model(message_id="999"))
    assert not result.ok
    assert "not found" in result.content.lower()


async def test_draft_persists(backend, drafts, tmp_store):
    t = tool(backend, drafts, "mail.draft")
    args = t.args_model(to=["alice@example.com"], subject="Re: Lunch", body="Sure, noon works!")
    result = await t.handler(args)
    assert result.ok
    draft_id = result.data["draft_id"]
    row = tmp_store.conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    assert row["subject"] == "Re: Lunch"
    assert row["body"] == "Sure, noon works!"
    assert row["to"] == "alice@example.com"
    assert row["sent"] == 0


async def test_send_from_draft_auto_confirm(backend, drafts, confirm_registry, tmp_store):
    # mail.send is DESTRUCTIVE: it always reaches the confirm gate. Here the
    # human approves, so it proceeds (AutoConfirm/--yes would refuse it).
    registry = confirm_registry
    registry.register_all(build_tools(backend, drafts))
    draft_res = await registry.execute(
        "mail.draft",
        {"to": ["alice@example.com"], "subject": "Re: Lunch", "body": "Sure!"},
    )
    draft_id = draft_res.data["draft_id"]
    send_res = await registry.execute("mail.send", {"draft_id": draft_id})
    assert send_res.ok
    assert len(backend.sent) == 1
    assert backend.sent[0].subject == "Re: Lunch"
    row = tmp_store.conn.execute("SELECT sent FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    assert row["sent"] == 1


async def test_send_blocked_by_auto_deny(backend, drafts, deny_registry, journal, tmp_store):
    deny_registry.register_all(build_tools(backend, drafts))
    draft_id = drafts.save(Draft(to=["alice@example.com"], subject="No", body="x"))
    result = await deny_registry.execute("mail.send", {"draft_id": draft_id})
    assert not result.ok
    assert "Denied by user" in result.content
    assert backend.sent == []  # nothing sent
    assert journal.recent(1)[0]["decision"] == "denied_by_user"
    row = tmp_store.conn.execute("SELECT sent FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    assert row["sent"] == 0


async def test_send_inline(backend, drafts, confirm_registry):
    registry = confirm_registry
    registry.register_all(build_tools(backend, drafts))
    result = await registry.execute(
        "mail.send",
        {"to": ["carol@example.com"], "subject": "Hi", "body": "Inline message"},
    )
    assert result.ok
    assert len(backend.sent) == 1
    assert backend.sent[0].to == ["carol@example.com"]


async def test_send_missing_draft_fails_cleanly(backend, drafts, confirm_registry):
    registry = confirm_registry
    registry.register_all(build_tools(backend, drafts))
    result = await registry.execute("mail.send", {"draft_id": 4242})
    assert not result.ok
    assert "No draft with id 4242" in result.content
    assert backend.sent == []


def test_send_validator_rejects_both_forms():
    with pytest.raises(ValidationError, match="not both"):
        MailSendArgs(draft_id=1, to=["x@example.com"], subject="s", body="b")


def test_send_validator_rejects_neither_form():
    with pytest.raises(ValidationError, match="either draft_id or inline"):
        MailSendArgs()


def test_send_validator_rejects_partial_inline():
    with pytest.raises(ValidationError, match="all of to, subject, body"):
        MailSendArgs(to=["x@example.com"])


def test_draft_requires_recipient():
    t = build_tools(MockMailBackend(), None)
    draft_tool = next(d for d in t if d.name == "mail.draft")
    with pytest.raises(ValidationError):
        draft_tool.args_model(to=[], subject="s", body="b")
