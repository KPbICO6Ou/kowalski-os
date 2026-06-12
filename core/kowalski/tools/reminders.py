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


class ReminderListArgs(BaseModel):
    include_done: bool = Field(
        default=False, description="Also include already delivered/missed reminders"
    )


class ReminderCancelArgs(BaseModel):
    reminder_id: int = Field(description="ID of the pending reminder to cancel")


def build_tools(scheduler: ReminderScheduler) -> list[ToolDef]:
    async def reminders_create(args: ReminderCreateArgs) -> ToolResult:
        due = datetime.fromisoformat(args.when)
        reminder_id = scheduler.add_reminder(args.text, due)
        return ToolResult(
            ok=True,
            content=f"Reminder #{reminder_id} set for {args.when}: {args.text}",
            data={"id": reminder_id, "due_at": args.when},
        )

    async def reminders_list(args: ReminderListArgs) -> ToolResult:
        rows = scheduler.list_reminders(include_done=args.include_done)
        if not rows:
            return ToolResult(ok=True, content="No reminders.", data=[])
        lines = []
        for row in rows:
            status = ""
            if row["delivered"]:
                status = " [missed]" if row["missed"] else " [delivered]"
            lines.append(f"#{row['id']} {row['due_at']} — {row['text']}{status}")
        listing = "\n".join(lines)
        return ToolResult(
            ok=True,
            content=f"{len(rows)} reminders:\n{listing}",
            data=[dict(row) for row in rows],
        )

    async def reminders_cancel(args: ReminderCancelArgs) -> ToolResult:
        error = scheduler.cancel_reminder(args.reminder_id)
        if error:
            return ToolResult(ok=False, content=error)
        return ToolResult(
            ok=True,
            content=f"Reminder #{args.reminder_id} cancelled.",
            data={"id": args.reminder_id},
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
        ),
        ToolDef(
            name="reminders.list",
            description=(
                "List pending reminders ordered by due time; include_done=true also "
                "shows delivered and missed ones."
            ),
            args_model=ReminderListArgs,
            risk=RiskLevel.READ,
            handler=reminders_list,
        ),
        ToolDef(
            name="reminders.cancel",
            description="Cancel a pending reminder by its ID (see reminders.list).",
            args_model=ReminderCancelArgs,
            risk=RiskLevel.WRITE,
            handler=reminders_cancel,
        ),
    ]
