"""MailController: backend reads, daemon-streamed AI actions, deterministic send.

The mailbox is the in-memory MockMailBackend seeded with messages; AI streaming
runs against the FakeDaemon fixture — no GTK, no network, no IMAP."""

from __future__ import annotations

import pytest

from kowalski.mail import Message, MockMailBackend
from kowui.client import OmniClient
from kowui.mail_controller import (
    MailController,
    reply_prompt,
    reply_subject,
    summarize_prompt,
)


def seeded_backend() -> MockMailBackend:
    return MockMailBackend(seed=[
        Message(id="1", folder="INBOX", from_addr="ivan@example.com", to=["me@example.com"],
                subject="Meeting moved", date="2026-07-20", snippet="the meeting is moved",
                unread=True, body_text="Hi, the meeting is moved to Friday. Ivan"),
        Message(id="2", folder="INBOX", from_addr="shop@example.com", to=["me@example.com"],
                subject="Your invoice", date="2026-07-21", snippet="invoice attached",
                unread=False, body_text="Invoice #42 attached."),
    ])


class RecordingCallbacks:
    def __init__(self):
        self.folders = []
        self.messages = []
        self.opened = []
        self.tokens = []
        self.done = 0
        self.sent = []
        self.errors = []

    def on_folders(self, folders):
        self.folders.append(folders)

    def on_messages(self, summaries):
        self.messages.append(summaries)

    def on_message(self, message):
        self.opened.append(message)

    def on_ai_token(self, text):
        self.tokens.append(text)

    def on_ai_done(self):
        self.done += 1

    def on_sent(self, detail):
        self.sent.append(detail)

    def on_error(self, message):
        self.errors.append(message)


@pytest.mark.asyncio
async def test_search_and_open_deliver_backend_data():
    cb = RecordingCallbacks()
    controller = MailController(seeded_backend(), None, cb)
    await controller.search("")
    assert len(cb.messages[0]) == 2  # empty query lists everything
    await controller.search("invoice")
    assert [s.id for s in cb.messages[1]] == ["2"]
    await controller.open_message("1")
    assert cb.opened[0].body_text.startswith("Hi, the meeting")
    assert not cb.errors


@pytest.mark.asyncio
async def test_ai_action_streams_tokens_from_daemon(fake_daemon, short_sock_path):
    cb = RecordingCallbacks()
    controller = MailController(seeded_backend(), OmniClient(short_sock_path), cb)
    message = await controller.backend.read("1")
    await controller.summarize(message)
    assert "".join(cb.tokens) == "Hello, world"
    assert cb.done == 1
    assert not cb.errors
    prompt_sent = fake_daemon.asks[0]["prompt"]
    assert "Meeting moved" in prompt_sent and "moved to Friday" in prompt_sent


@pytest.mark.asyncio
async def test_ai_without_daemon_reports_error():
    cb = RecordingCallbacks()
    controller = MailController(seeded_backend(), None, cb)
    message = await controller.backend.read("1")
    await controller.summarize(message)
    assert cb.errors and "kow serve" in cb.errors[0]
    assert not cb.tokens


@pytest.mark.asyncio
async def test_send_reply_goes_to_sender_with_re_subject():
    backend = seeded_backend()
    cb = RecordingCallbacks()
    controller = MailController(backend, None, cb)
    message = await backend.read("1")
    await controller.send_reply(message, "Ок, увидимся в пятницу.")
    assert len(backend.sent) == 1
    draft = backend.sent[0]
    assert draft.to == ["ivan@example.com"]
    assert draft.subject == "Re: Meeting moved"
    assert cb.sent and "ivan@example.com" in cb.sent[0]


@pytest.mark.asyncio
async def test_send_empty_reply_is_rejected():
    backend = seeded_backend()
    cb = RecordingCallbacks()
    controller = MailController(backend, None, cb)
    message = await backend.read("1")
    await controller.send_reply(message, "   ")
    assert not backend.sent
    assert cb.errors


def test_prompts_carry_the_email_and_reply_subject_prefixes_once():
    message = seeded_backend().messages["1"]
    assert "Meeting moved" in summarize_prompt(message)
    assert "reply" in reply_prompt(message).lower()
    assert reply_subject("Meeting moved") == "Re: Meeting moved"
    assert reply_subject("Re: Meeting moved") == "Re: Meeting moved"
