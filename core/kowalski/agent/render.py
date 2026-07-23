"""Terminal rendering of agent events, shared by every console front-end
(`kow ask`/`kow chat` here, `kow chat --voice` in the voice package) — so the
CLIs don't have to import each other's internals."""

from __future__ import annotations

import json
import sys

DIM = "\033[2m"
RESET = "\033[0m"


def summarize_kwargs(config) -> dict:
    """run_turn summarisation params from config (off => never trigger)."""
    if not config.get_bool("KOW_SUMMARIZE"):
        return {"summarize_after": 10**9}
    return {
        "summarize_after": config.get_int("KOW_SUMMARIZE_AFTER"),
        "keep": config.get_int("KOW_SUMMARIZE_KEEP"),
    }


def print_event(event, json_mode: bool = False) -> bool:
    """Render one agent event to stdout. Returns True if it was an error."""
    from .events import (
        DoneEvent,
        ErrorEvent,
        PlanEvent,
        PlanStepEvent,
        TokenEvent,
        ToolCallEvent,
        ToolResultEvent,
    )

    if json_mode:
        print(json.dumps(event.to_dict(), ensure_ascii=False), flush=True)
        return isinstance(event, ErrorEvent)
    if isinstance(event, PlanEvent):
        print("Plan:")
        for k, step in enumerate(event.steps, start=1):
            print(f"  {k}. {step}")
    elif isinstance(event, PlanStepEvent):
        k, total = event.index + 1, event.total
        if event.status == "start":
            print(f"\n▶ step {k}/{total}: {event.description}")
        else:
            print(f"{DIM}✓ step {k}/{total}{RESET}")
    elif isinstance(event, TokenEvent):
        print(event.text, end="", flush=True)
    elif isinstance(event, ToolCallEvent):
        print(f"\n{DIM}→ {event.tool}({json.dumps(event.args, ensure_ascii=False)}){RESET}")
    elif isinstance(event, ToolResultEvent):
        status = "✓" if event.ok else "✗"
        print(f"{DIM}{status} {event.content[:200]}{RESET}")
    elif isinstance(event, DoneEvent):
        print()
    elif isinstance(event, ErrorEvent):
        print(f"\nerror: {event.message}", file=sys.stderr)
        return True
    return False
