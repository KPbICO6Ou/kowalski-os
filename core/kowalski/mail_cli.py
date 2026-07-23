"""`kow mail` subcommands: direct mailbox access from the terminal
(search/read/folders) over the same backend the agent's mail.* tools use
(KOW_MAIL_BACKEND). The write side (draft/send) stays behind the agent's
confirmation flow on purpose."""

from __future__ import annotations

import asyncio
import sys

from .config import Config


def cmd_mail(args) -> int:
    from .mail import build_backend

    if not getattr(args, "mail_command", None):
        print("usage: kow mail {search|read|folders}", file=sys.stderr)
        return 2
    config = Config.load()
    backend = build_backend(config)
    if backend is None:
        print("mail: KOW_MAIL_BACKEND=imap but the 'mail' extra isn't installed "
              "(pip install 'kowalski[mail]').", file=sys.stderr)
        return 2
    return asyncio.run(run_mail(args, backend))


async def run_mail(args, backend) -> int:
    try:
        if args.mail_command == "folders":
            for name in await backend.list_folders():
                print(name)
            return 0
        if args.mail_command == "search":
            summaries = await backend.search(args.query, folder=args.folder, limit=args.limit)
            if not summaries:
                print("No messages found.")
                return 0
            for summary in summaries:
                flag = "*" if summary.unread else " "
                print(f"{flag} [{summary.id}] {summary.date}  "
                      f"{summary.from_addr}  —  {summary.subject}")
            return 0
        if args.mail_command == "read":
            message = await backend.read(args.message_id)
            print(f"Subject: {message.subject}")
            print(f"From: {message.from_addr}")
            print(f"To: {', '.join(message.to)}")
            print(f"Date: {message.date}\n")
            print(message.body_text)
            return 0
    except (KeyError, LookupError) as exc:
        print(f"Message not found: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # IMAP/connection errors must not dump a traceback
        print(f"mail error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("usage: kow mail {search|read|folders}", file=sys.stderr)
    return 2
