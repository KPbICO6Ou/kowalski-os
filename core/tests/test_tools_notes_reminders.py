from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from kowalski.scheduler import ReminderScheduler
from kowalski.tools.notes import NoteCreateArgs, build_tools as build_notes
from kowalski.tools.reminders import (
    ReminderCancelArgs,
    ReminderCreateArgs,
    ReminderListArgs,
    build_tools as build_reminders,
)


def reminder_tool(scheduler: ReminderScheduler, name: str):
    return next(t for t in build_reminders(scheduler) if t.name == name)


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


async def test_reminders_list_pending_only(tmp_store):
    scheduler = ReminderScheduler(tmp_store)
    due = (datetime.now() + timedelta(hours=1)).isoformat(timespec="seconds")
    tmp_store.conn.execute("INSERT INTO reminders (text, due_at) VALUES (?, ?)", ("soon", due))
    tmp_store.conn.execute(
        "INSERT INTO reminders (text, due_at, delivered, missed) VALUES (?, ?, 1, 1)",
        ("old one", "2026-01-01T09:00:00"),
    )
    tmp_store.conn.commit()
    tool = reminder_tool(scheduler, "reminders.list")

    result = await tool.handler(ReminderListArgs())
    assert result.ok
    assert [r["text"] for r in result.data] == ["soon"]
    assert "soon" in result.content and "old one" not in result.content

    result = await tool.handler(ReminderListArgs(include_done=True))
    assert {r["text"] for r in result.data} == {"soon", "old one"}
    assert "[missed]" in result.content


async def test_reminders_list_empty(tmp_store):
    tool = reminder_tool(ReminderScheduler(tmp_store), "reminders.list")
    result = await tool.handler(ReminderListArgs())
    assert result.ok
    assert result.data == []


async def test_reminders_cancel_removes_row(tmp_store):
    scheduler = ReminderScheduler(tmp_store)  # not started: no APScheduler job
    reminder_id = scheduler.add_reminder("cancel me", datetime.now() + timedelta(hours=1))
    tool = reminder_tool(scheduler, "reminders.cancel")
    result = await tool.handler(ReminderCancelArgs(reminder_id=reminder_id))
    assert result.ok
    assert tmp_store.conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0


async def test_reminders_cancel_removes_scheduler_job(tmp_store):
    scheduler = ReminderScheduler(tmp_store)
    scheduler.start()
    try:
        reminder_id = scheduler.add_reminder("cancel me", datetime.now() + timedelta(hours=1))
        assert scheduler._scheduler.get_job(f"reminder-{reminder_id}") is not None
        tool = reminder_tool(scheduler, "reminders.cancel")
        result = await tool.handler(ReminderCancelArgs(reminder_id=reminder_id))
        assert result.ok
        assert scheduler._scheduler.get_job(f"reminder-{reminder_id}") is None
        assert tmp_store.conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0
    finally:
        scheduler.shutdown()


async def test_reminders_cancel_missing_id(tmp_store):
    tool = reminder_tool(ReminderScheduler(tmp_store), "reminders.cancel")
    result = await tool.handler(ReminderCancelArgs(reminder_id=4242))
    assert not result.ok
    assert "no reminder with id 4242" in result.content


async def test_reminders_cancel_delivered_rejected(tmp_store):
    tmp_store.conn.execute(
        "INSERT INTO reminders (text, due_at, delivered) VALUES (?, ?, 1)",
        ("done", "2026-01-01T09:00:00"),
    )
    tmp_store.conn.commit()
    reminder_id = tmp_store.conn.execute("SELECT id FROM reminders").fetchone()["id"]
    tool = reminder_tool(ReminderScheduler(tmp_store), "reminders.cancel")
    result = await tool.handler(ReminderCancelArgs(reminder_id=reminder_id))
    assert not result.ok
    assert "already delivered" in result.content
    assert tmp_store.conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 1


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
