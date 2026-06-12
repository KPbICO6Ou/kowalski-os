"""Reminder scheduling: APScheduler wrapper + re-arm on startup."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from . import platform
from .store import Store

log = logging.getLogger(__name__)


class ReminderScheduler:
    def __init__(self, store: Store):
        self._store = store
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        self._scheduler.start()
        self._rearm()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def add_reminder(self, text: str, due_at: datetime) -> int:
        cur = self._store.conn.execute(
            "INSERT INTO reminders (text, due_at) VALUES (?, ?)",
            (text, due_at.isoformat(timespec="seconds")),
        )
        self._store.conn.commit()
        reminder_id = int(cur.lastrowid or 0)
        if self._scheduler.running:
            self._schedule(reminder_id, text, due_at)
        return reminder_id

    def list_reminders(self, include_done: bool = False) -> list[sqlite3.Row]:
        query = "SELECT id, text, due_at, delivered, missed FROM reminders"
        if not include_done:
            query += " WHERE delivered = 0"
        query += " ORDER BY due_at"
        return self._store.conn.execute(query).fetchall()

    def cancel_reminder(self, reminder_id: int) -> str | None:
        """Cancel a pending reminder. Returns an error message, or None on success."""
        row = self._store.conn.execute(
            "SELECT delivered FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
        if row is None:
            return f"no reminder with id {reminder_id}"
        if row["delivered"]:
            return f"reminder {reminder_id} was already delivered and cannot be cancelled"
        try:
            self._scheduler.remove_job(f"reminder-{reminder_id}")
        except JobLookupError:
            pass  # not scheduled (e.g. scheduler not started) — row delete is enough
        self._store.conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        self._store.conn.commit()
        return None

    def _schedule(self, reminder_id: int, text: str, due_at: datetime) -> None:
        self._scheduler.add_job(
            self._fire,
            DateTrigger(run_date=due_at),
            args=[reminder_id, text, False],
            id=f"reminder-{reminder_id}",
            replace_existing=True,
        )

    def _rearm(self) -> None:
        """Re-arm undelivered reminders; fire missed ones immediately."""
        rows = self._store.conn.execute(
            "SELECT id, text, due_at FROM reminders WHERE delivered = 0"
        ).fetchall()
        now = datetime.now().astimezone()
        for row in rows:
            due = datetime.fromisoformat(row["due_at"])
            if due.tzinfo is None:
                due = due.astimezone()
            if due <= now:
                asyncio.get_event_loop().create_task(self._fire(row["id"], row["text"], True))
            else:
                self._schedule(row["id"], row["text"], due)

    async def _fire(self, reminder_id: int, text: str, missed: bool) -> None:
        title = "Missed reminder" if missed else "Reminder"
        try:
            await platform.notify(title, text)
        except Exception:
            log.exception("notification failed for reminder %s", reminder_id)
        self._store.conn.execute(
            "UPDATE reminders SET delivered = 1, missed = ? WHERE id = ?",
            (int(missed), reminder_id),
        )
        self._store.conn.commit()
