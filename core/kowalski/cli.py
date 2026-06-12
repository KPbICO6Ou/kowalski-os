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
    ask.add_argument("-c", "--conversation", help="conversation ID to continue")
    ask.add_argument(
        "--continue",
        dest="continue_",
        action="store_true",
        help="continue the most recent conversation",
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
    if args.command == "serve":
        from .daemon import run_daemon

        return asyncio.run(run_daemon(api=args.api))
    if args.command == "tools" and args.tools_command == "list":
        return cmd_tools_list(args)
    if args.command == "journal" and args.journal_command == "tail":
        return cmd_journal_tail(args)
    parser.print_help()
    return 1


def _build_runtime(confirmer):
    """Config -> store -> scheduler -> registry, shared by ask/serve/tools."""
    from .bootstrap import build_default_registry
    from .scheduler import ReminderScheduler
    from .store import Store

    config = Config.load()
    store = Store(config.get_path("KOW_DB_PATH"))
    scheduler = ReminderScheduler(store)
    registry = build_default_registry(config, store, scheduler, confirmer)
    return config, store, scheduler, registry


async def cmd_ask(args) -> int:
    import uuid

    from .agent.events import DoneEvent, ErrorEvent, TokenEvent, ToolCallEvent, ToolResultEvent
    from .agent.loop import AgentLoop
    from .bootstrap import build_llm
    from .conversations import ConversationStore, run_turn
    from .policy import AutoConfirm, InteractiveCliConfirmation

    confirmer = AutoConfirm() if args.yes else InteractiveCliConfirmation()
    config, store, scheduler, registry = _build_runtime(confirmer)
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
    loop = AgentLoop(llm, registry, max_iterations=config.get_int("KOW_MAX_ITERATIONS"))

    exit_code = 0
    try:
        async for event in run_turn(loop, args.prompt, conversation_id, conversations):
            if args.json:
                print(json.dumps(event.to_dict(), ensure_ascii=False), flush=True)
                continue
            if isinstance(event, TokenEvent):
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
