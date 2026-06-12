"""reminders.* tools: scheduled notifications."""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, Field, field_validator

from ..scheduler import ReminderScheduler
from .base import RiskLevel, ToolDef, ToolResult

PAST_GRACE = timedelta(seconds=60)


class ReminderCreateArgs(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    when: str = Field(description="ISO-8601 local datetime, e.g. 2026-06-12T15:30:00")

    @field_validator("when")
    @classmethod
    def must_be_future(cls, value: str) -> str:
        try:
            due = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"not a valid ISO-8601 datetime: {value}") from exc
        now = datetime.now(due.tzinfo) if due.tzinfo else datetime.now()
        if due < now - PAST_GRACE:
            raise ValueError(f"reminder time {value} is in the past (now: {now.isoformat()})")
        return value


def build_tools(scheduler: ReminderScheduler) -> list[ToolDef]:
    async def reminders_create(args: ReminderCreateArgs) -> ToolResult:
        due = datetime.fromisoformat(args.when)
        reminder_id = scheduler.add_reminder(args.text, due)
        return ToolResult(
            ok=True,
            content=f"Reminder #{reminder_id} set for {args.when}: {args.text}",
            data={"id": reminder_id, "due_at": args.when},
        )

    return [
        ToolDef(
            name="reminders.create",
            description=(
                "Set a reminder that fires a desktop notification at the given time. "
                "The 'when' argument must be an ISO-8601 local datetime."
            ),
            args_model=ReminderCreateArgs,
            risk=RiskLevel.WRITE,
            handler=reminders_create,
        )
    ]
