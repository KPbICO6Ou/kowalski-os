"""kow CLI: ask (in-process agent, no daemon), serve, tools list, journal tail."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import __version__
from .config import Config

DIM = "\033[2m"
RESET = "\033[0m"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kow", description="Kowalski OS agent CLI")
    parser.add_argument("--version", action="version", version=f"kow {__version__}")
    sub = parser.add_subparsers(dest="command")

    ask = sub.add_parser("ask", help="ask the agent (one-shot, in-process)")
    ask.add_argument("prompt", help="what to ask")
    ask.add_argument("--model", help="override OLLAMA_MODEL")
    ask.add_argument("--yes", action="store_true", help="auto-approve confirmations (not destructive)")
    ask.add_argument("--json", action="store_true", help="emit raw events as JSON lines")
    ask.add_argument(
        "--plan",
        action="store_true",
        help="plan-then-execute: decompose the goal into steps before acting",
    )
    ask.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="preview: mutating tools are not executed, only reported",
    )
    ask.add_argument("-c", "--conversation", help="conversation ID to continue")
    ask.add_argument(
        "--continue",
        "--resume",
        dest="continue_",
        action="store_true",
        help="continue the most recent conversation (--resume is an alias)",
    )

    chat = sub.add_parser("chat", help="interactive REPL (stays open, one conversation)")
    chat.add_argument("--model", help="override OLLAMA_MODEL")
    chat.add_argument("--yes", action="store_true", help="auto-approve confirmations (not destructive)")
    chat.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="preview: mutating tools are not executed, only reported",
    )
    chat.add_argument("-c", "--conversation", help="resume a specific conversation ID")
    chat.add_argument(
        "--continue",
        "--resume",
        dest="continue_",
        action="store_true",
        help="resume the most recent conversation (--resume is an alias)",
    )

    serve = sub.add_parser("serve", help="run the kow-core daemon")
    serve.add_argument("--api", action="store_true", help="enable the debug REST API")

    tools = sub.add_parser("tools", help="tool registry")
    tools_sub = tools.add_subparsers(dest="tools_command")
    tools_list = tools_sub.add_parser("list", help="list registered tools")
    tools_list.add_argument("--schemas", action="store_true", help="dump JSON schemas")

    journal = sub.add_parser("journal", help="action journal")
    journal_sub = journal.add_subparsers(dest="journal_command")
    journal_tail = journal_sub.add_parser("tail", help="show recent journal entries")
    journal_tail.add_argument("-n", type=int, default=20, dest="limit")

    args = parser.parse_args(argv)

    if args.command == "ask":
        return asyncio.run(cmd_ask(args))
    if args.command == "chat":
        return asyncio.run(cmd_chat(args))
    if args.command == "serve":
        from .daemon import run_daemon

        return asyncio.run(run_daemon(api=args.api))
    if args.command == "tools" and args.tools_command == "list":
        return cmd_tools_list(args)
    if args.command == "journal" and args.journal_command == "tail":
        return cmd_journal_tail(args)
    parser.print_help()
    return 1


def _build_runtime(confirmer, dry_run: bool = False):
    """Config -> store -> scheduler -> registry, shared by ask/serve/tools."""
    from .bootstrap import build_default_registry
    from .scheduler import ReminderScheduler
    from .store import Store

    config = Config.load()
    store = Store(config.get_path("KOW_DB_PATH"))
    scheduler = ReminderScheduler(store)
    registry = build_default_registry(config, store, scheduler, confirmer)
    if dry_run:
        registry.dry_run = True
    return config, store, scheduler, registry


def _summarize_kwargs(config) -> dict:
    """run_turn summarisation params from config (off => never trigger)."""
    if not config.get_bool("KOW_SUMMARIZE"):
        return {"summarize_after": 10**9}
    return {
        "summarize_after": config.get_int("KOW_SUMMARIZE_AFTER"),
        "keep": config.get_int("KOW_SUMMARIZE_KEEP"),
    }


def _print_event(event, json_mode: bool = False) -> bool:
    """Render one agent event to stdout. Returns True if it was an error."""
    from .agent.events import (
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


async def cmd_ask(args) -> int:
    import uuid

    from .agent.loop import AgentLoop
    from .agent.planner import Planner
    from .bootstrap import build_llm
    from .conversations import ConversationStore, run_turn
    from .policy import AutoConfirm, InteractiveCliConfirmation

    confirmer = AutoConfirm() if args.yes else InteractiveCliConfirmation()
    config, store, scheduler, registry = _build_runtime(confirmer, dry_run=args.dry_run)
    conversations = ConversationStore(store)

    conversation_id = args.conversation
    if args.continue_:
        conversation_id = conversations.last_conversation_id()
        if conversation_id is None:
            print("no previous conversation to continue", file=sys.stderr)
            store.close()
            return 1
    new_conversation = conversation_id is None
    if new_conversation:
        conversation_id = uuid.uuid4().hex

    scheduler.start()
    llm = build_llm(config, model_override=args.model or "")
    context_provider = getattr(registry, "context_provider", None)

    if args.plan:
        planner = Planner(
            llm,
            registry,
            max_iterations_per_step=config.get_int("KOW_MAX_ITERATIONS"),
            context_provider=context_provider,
        )
        events = _run_planner_turn(
            planner, args.prompt, conversation_id, conversations
        )
    else:
        loop = AgentLoop(
            llm,
            registry,
            max_iterations=config.get_int("KOW_MAX_ITERATIONS"),
            context_provider=context_provider,
        )
        events = run_turn(
            loop, args.prompt, conversation_id, conversations, **_summarize_kwargs(config)
        )

    exit_code = 0
    try:
        async for event in events:
            if _print_event(event, json_mode=args.json):
                exit_code = 1
        if not args.json and new_conversation:
            print(
                f"{DIM}(conversation: {conversation_id}"
                f' — continue with: kow ask --continue "..."){RESET}'
            )
    finally:
        scheduler.shutdown()
        store.close()
    return exit_code


async def _run_planner_turn(planner, prompt, conversation_id, conversations):
    """Drive a Planner.run while persisting the conversation like run_turn.

    The planner manages its own per-step history internally, so we only persist
    the original user prompt and the final synthesized assistant answer."""
    from .agent.events import DoneEvent

    if conversations is not None:
        conversations.touch(conversation_id, title_hint=prompt)
        conversations.append(conversation_id, "user", prompt)

    answer = None
    async for event in planner.run(prompt, conversation_id=conversation_id):
        if isinstance(event, DoneEvent):
            answer = event.answer
        yield event

    if conversations is not None and answer is not None:
        conversations.append(conversation_id, "assistant", answer)


async def cmd_chat(args) -> int:
    """Interactive in-process REPL: one persistent conversation, no daemon."""
    import uuid

    from .agent.loop import AgentLoop
    from .bootstrap import build_llm
    from .conversations import ConversationStore, run_turn
    from .policy import AutoConfirm, InteractiveCliConfirmation

    try:
        import readline  # noqa: F401  (enables line editing/history in input())
    except Exception:
        pass

    confirmer = AutoConfirm() if args.yes else InteractiveCliConfirmation()
    config, store, scheduler, registry = _build_runtime(confirmer, dry_run=args.dry_run)
    conversations = ConversationStore(store)

    conversation_id = args.conversation
    if args.continue_ and not conversation_id:
        conversation_id = conversations.last_conversation_id()
    resumed = conversation_id is not None
    if conversation_id is None:
        conversation_id = uuid.uuid4().hex

    scheduler.start()
    llm = build_llm(config, model_override=args.model or "")
    loop = AgentLoop(
        llm,
        registry,
        max_iterations=config.get_int("KOW_MAX_ITERATIONS"),
        context_provider=getattr(registry, "context_provider", None),
    )

    suffix = " (resumed)" if resumed else ""
    print(
        f"{DIM}kow chat — conversation {conversation_id}{suffix}. "
        f"Type 'exit' or press Ctrl-D to quit.{RESET}"
    )
    try:
        while True:
            try:
                line = input("kow› ")
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                continue
            text = line.strip()
            if not text:
                continue
            if text in ("exit", "quit", ":q"):
                break
            try:
                async for event in run_turn(
                    loop, text, conversation_id, conversations, **_summarize_kwargs(config)
                ):
                    _print_event(event)
            except KeyboardInterrupt:
                print("\n(interrupted)")
    finally:
        scheduler.shutdown()
        store.close()
    print(f"{DIM}(conversation: {conversation_id} — reopen with: kow chat --resume){RESET}")
    return 0


def cmd_tools_list(args) -> int:
    from .policy import AutoDeny

    _, store, _, registry = _build_runtime(AutoDeny())
    try:
        if args.schemas:
            print(json.dumps(registry.schemas_for_ollama(), ensure_ascii=False, indent=2))
            return 0
        width = max(len(t.name) for t in registry.list())
        for tool in registry.list():
            print(f"{tool.name:<{width}}  [{tool.risk:<11}]  {tool.description}")
    finally:
        store.close()
    return 0


def cmd_journal_tail(args) -> int:
    from .journal import ActionJournal
    from .store import Store

    config = Config.load()
    store = Store(config.get_path("KOW_DB_PATH"))
    try:
        entries = ActionJournal(store).recent(args.limit)
        if not entries:
            print("journal is empty")
            return 0
        for entry in reversed(entries):
            ok = {1: "ok", 0: "FAIL", None: "-"}[entry["result_ok"]]
            print(
                f"{entry['ts']}  {entry['tool']:<22} {entry['decision']:<16} {ok:<4}"
                f" {entry['duration_ms'] or '':>6}  {entry['args_json'][:60]}"
            )
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
