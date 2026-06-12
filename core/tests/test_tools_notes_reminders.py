from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from kowalski.scheduler import ReminderScheduler
from kowalski.tools.notes import NoteCreateArgs, build_tools as build_notes
from kowalski.tools.reminders import ReminderCreateArgs, build_tools as build_reminders


async def test_note_create(tmp_store):
    tool = build_notes(tmp_store)[0]
    result = await tool.handler(NoteCreateArgs(title="Idea", body="text", tags=["a", "b"]))
    assert result.ok
    row = tmp_store.conn.execute("SELECT * FROM notes").fetchone()
    assert row["title"] == "Idea"
    assert row["tags"] == "a,b"


def test_note_title_required():
    with pytest.raises(ValidationError):
        NoteCreateArgs(title="")


async def test_reminder_create_persists(tmp_store):
    scheduler = ReminderScheduler(tmp_store)  # not started: only DB insert
    tool = build_reminders(scheduler)[0]
    due = (datetime.now() + timedelta(hours=1)).isoformat(timespec="seconds")
    result = await tool.handler(ReminderCreateArgs(text="call mom", when=due))
    assert result.ok
    row = tmp_store.conn.execute("SELECT * FROM reminders").fetchone()
    assert row["text"] == "call mom"
    assert row["delivered"] == 0


def test_reminder_past_rejected():
    past = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    with pytest.raises(ValidationError, match="in the past"):
        ReminderCreateArgs(text="too late", when=past)


def test_reminder_bad_datetime_rejected():
    with pytest.raises(ValidationError, match="ISO-8601"):
        ReminderCreateArgs(text="x", when="tomorrow at noon")


async def test_scheduler_rearm_marks_missed(tmp_store, monkeypatch):
    async def fake_notify(title, body):
        return True

    monkeypatch.setattr("kowalski.platform.notify", fake_notify)
    past = (datetime.now() - timedelta(minutes=10)).isoformat(timespec="seconds")
    tmp_store.conn.execute(
        "INSERT INTO reminders (text, due_at) VALUES (?, ?)", ("missed one", past)
    )
    tmp_store.conn.commit()
    scheduler = ReminderScheduler(tmp_store)
    scheduler.start()
    try:
        import asyncio

        await asyncio.sleep(0.2)  # let the missed-fire task run
        row = tmp_store.conn.execute("SELECT * FROM reminders").fetchone()
        assert row["delivered"] == 1
        assert row["missed"] == 1
    finally:
        scheduler.shutdown()
