"""plan.* tools: a visible to-do list the agent maintains during a turn.

This mirrors ARIA's create_plan / update_plan / show_plan: the model lays out
a short checklist for a multi-step job, then ticks items off as it works. The
rendered list is returned as tool result content, so the user sees progress
streamed back.

State is held in a single :class:`Checklist` captured in the factory closure
returned by :func:`build_checklist_tools` — one checklist per registry/runtime,
so concurrent runtimes built from separate factory calls don't collide.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .base import RiskLevel, ToolDef, ToolResult

Status = Literal["todo", "doing", "done"]

_MARKS: dict[str, str] = {"todo": "☐", "doing": "▶", "done": "✓"}


class Checklist:
    """An ordered list of steps, each with a todo/doing/done status."""

    def __init__(self) -> None:
        self._steps: list[str] = []
        self._statuses: list[Status] = []

    def replace(self, steps: list[str]) -> None:
        self._steps = list(steps)
        self._statuses = ["todo"] * len(steps)

    def set_status(self, step: int, status: Status) -> None:
        """``step`` is 1-based. Raises IndexError if out of range."""
        if step < 1 or step > len(self._steps):
            raise IndexError(step)
        self._statuses[step - 1] = status

    def render(self) -> str:
        if not self._steps:
            return "(no checklist yet)"
        done = sum(1 for s in self._statuses if s == "done")
        total = len(self._steps)
        lines = [f"Checklist ({done}/{total} done):"]
        for idx, (text, status) in enumerate(zip(self._steps, self._statuses), start=1):
            lines.append(f"{_MARKS[status]} {idx}. {text}")
        return "\n".join(lines)

    def data(self) -> dict:
        return {
            "steps": [
                {"index": i, "text": t, "status": s}
                for i, (t, s) in enumerate(zip(self._steps, self._statuses), start=1)
            ],
            "done": sum(1 for s in self._statuses if s == "done"),
            "total": len(self._steps),
        }

    def __len__(self) -> int:
        return len(self._steps)


class PlanCreateArgs(BaseModel):
    steps: list[str] = Field(min_length=1, description="Ordered checklist steps, at least one.")


class PlanUpdateArgs(BaseModel):
    step: int = Field(ge=1, description="1-based index of the step to update.")
    status: Status = Field(description="New status: todo, doing, or done.")


class PlanShowArgs(BaseModel):
    pass


def build_checklist_tools() -> list[ToolDef]:
    """Return plan.create / plan.update / plan.show backed by one shared Checklist."""
    checklist = Checklist()

    async def plan_create(args: PlanCreateArgs) -> ToolResult:
        checklist.replace(args.steps)
        rendered = checklist.render()
        return ToolResult(ok=True, content=rendered, data=checklist.data())

    async def plan_update(args: PlanUpdateArgs) -> ToolResult:
        try:
            checklist.set_status(args.step, args.status)
        except IndexError:
            return ToolResult(
                ok=False,
                content=(
                    f"No step {args.step}; checklist has {len(checklist)} step(s).\n"
                    f"{checklist.render()}"
                ),
                data=checklist.data(),
            )
        rendered = checklist.render()
        return ToolResult(ok=True, content=rendered, data=checklist.data())

    async def plan_show(args: PlanShowArgs) -> ToolResult:
        return ToolResult(ok=True, content=checklist.render(), data=checklist.data())

    return [
        ToolDef(
            name="plan.create",
            description=(
                "Create a visible checklist for a multi-step task. Call this FIRST "
                "whenever a request needs several steps, listing each step in order. "
                "Replaces any existing checklist. Returns the rendered list shown to "
                "the user."
            ),
            args_model=PlanCreateArgs,
            risk=RiskLevel.READ,
            handler=plan_create,
        ),
        ToolDef(
            name="plan.update",
            description=(
                "Update one checklist step's status. Mark a step 'doing' before you "
                "start it and 'done' the moment you finish, so the user can follow "
                "your progress. 'step' is 1-based."
            ),
            args_model=PlanUpdateArgs,
            risk=RiskLevel.READ,
            handler=plan_update,
        ),
        ToolDef(
            name="plan.show",
            description="Show the current checklist with each step's status and a done/total count.",
            args_model=PlanShowArgs,
            risk=RiskLevel.READ,
            handler=plan_show,
        ),
    ]
