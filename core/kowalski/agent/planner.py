"""Plan-then-execute: decompose a goal into steps and execute them in order.

An opt-in alternative to the default ReAct loop (AgentLoop). The Planner first
asks the LLM for an explicit step list, then runs each step as its own short
AgentLoop turn, threading the running results through a shared history, and
finishes with a synthesis turn that produces the final answer.

It is deliberately robust: make_plan never raises (falling back to a single
degenerate step), and run() re-emits the sub-loops' events without leaking
their intermediate DoneEvents as the final one."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from ..tools.registry import ToolRegistry
from .events import (
    AgentEvent,
    DoneEvent,
    ErrorEvent,
    PlanEvent,
    PlanStepEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from .llm import LLMClient
from .loop import AgentLoop

MAX_STEPS = 8

PLANNER_SYSTEM_PROMPT = """\
You are a planner. Decompose the user's goal into a short ordered list of
concrete steps that, executed in sequence, accomplish the goal.

Rules:
- Respond with ONLY a JSON array of short step strings, nothing else.
- Keep it minimal: prefer the fewest steps that get the job done (at most 8).
- Each step is a single imperative instruction, e.g. "Find recent PDF files".
- Do not include explanations, numbering, or markdown — only the JSON array.

Example: ["Find recent PDF files", "Pick the largest one", "Summarize it"]
"""


def _parse_plan(text: str) -> list[str]:
    """Extract a step list from raw model text. Robust to extra prose.

    Order of attempts: first JSON array in the text, then leading numbered /
    bulleted lines. Returns [] if nothing usable was found."""
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                steps = [str(item).strip() for item in parsed if str(item).strip()]
                if steps:
                    return steps
        except (TypeError, ValueError):
            pass

    steps = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip leading "1." / "1)" / "-" / "*" / "•" markers.
        stripped = re.sub(r"^(?:\d+[.)]|[-*•])\s+", "", line)
        if stripped != line and stripped:
            steps.append(stripped)
    return steps


class Planner:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        max_iterations_per_step: int = 6,
        context_provider=None,
    ):
        self.llm = llm
        self.registry = registry
        self.max_iterations_per_step = max_iterations_per_step
        self.context_provider = context_provider

    async def make_plan(self, goal: str) -> list[str]:
        """Ask the LLM for a step list. Never raises; degenerates to [goal]."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Goal: {goal}"},
        ]
        parts: list[str] = []
        try:
            async for chunk in self.llm.chat(messages, []):
                if chunk.content_delta:
                    parts.append(chunk.content_delta)
        except Exception:
            return [goal]

        steps = _parse_plan("".join(parts))
        if not steps:
            return [goal]
        return steps[:MAX_STEPS]

    def _new_loop(self) -> AgentLoop:
        return AgentLoop(
            self.llm,
            self.registry,
            max_iterations=self.max_iterations_per_step,
            context_provider=self.context_provider,
        )

    async def run(
        self, goal: str, conversation_id: str | None = None
    ) -> AsyncIterator[AgentEvent]:
        """Plan the goal, execute each step, then synthesize a final answer.

        Re-emits each sub-loop's Token/ToolCall/ToolResult events. A sub-loop's
        DoneEvent is captured (not propagated); only the synthesis turn emits the
        final DoneEvent. An ErrorEvent from any sub-loop stops the plan."""
        steps = await self.make_plan(goal)
        yield PlanEvent(goal=goal, steps=steps)

        numbered_plan = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
        history: list[dict[str, Any]] = []

        for i, step in enumerate(steps):
            yield PlanStepEvent(
                index=i, total=len(steps), description=step, status="start"
            )
            step_prompt = (
                f"Goal: {goal}\n\nFull plan:\n{numbered_plan}\n\n"
                f"Now execute step {i + 1}: {step}. "
                "Use tools as needed; report the result concisely."
            )
            answer_parts: list[str] = []
            errored = False
            async for event in self._new_loop().run(
                step_prompt, history=history, conversation_id=conversation_id
            ):
                if isinstance(event, DoneEvent):
                    answer_parts.append(event.answer)
                    continue
                if isinstance(event, ErrorEvent):
                    yield event
                    errored = True
                    break
                if isinstance(event, (TokenEvent, ToolCallEvent, ToolResultEvent)):
                    yield event
            if errored:
                return

            answer = "".join(answer_parts)
            history.append({"role": "user", "content": step_prompt})
            history.append({"role": "assistant", "content": answer})
            yield PlanStepEvent(
                index=i, total=len(steps), description=step, status="done"
            )

        synthesis_prompt = (
            "All plan steps are done. Give the user a concise final answer "
            f"for the original goal: {goal}"
        )
        final_parts: list[str] = []
        async for event in self._new_loop().run(
            synthesis_prompt, history=history, conversation_id=conversation_id
        ):
            if isinstance(event, DoneEvent):
                final_parts.append(event.answer)
                continue
            if isinstance(event, ErrorEvent):
                yield event
                return
            if isinstance(event, (TokenEvent, ToolCallEvent, ToolResultEvent)):
                yield event

        yield DoneEvent(answer="".join(final_parts))
