"""kow-mail entry point: the AI-first mail window.

Needs PyGObject/GTK3 (no terminal fallback — `kow mail` is the CLI). The mailbox
comes from the shared backend (KOW_MAIL_BACKEND: imap or mock); `--demo` seeds an
in-memory inbox so the window can be tried without credentials. AI actions talk
to the kow-core daemon."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .client import OmniClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kow-mail", description="Kowalski mail window")
    parser.add_argument("--version", action="version", version=f"kow-mail {__version__}")
    parser.add_argument("--socket", metavar="PATH", default=None, help="daemon socket path")
    parser.add_argument("--demo", action="store_true",
                        help="use a seeded in-memory inbox (no credentials needed)")
    return parser


def demo_backend():
    from kowalski.mail import Message, MockMailBackend

    return MockMailBackend(seed=[
        Message(id="1", folder="INBOX", from_addr="ivan@example.com", to=["you@example.com"],
                subject="Встреча переносится", date="2026-07-21 10:02", snippet="",
                unread=True,
                body_text="Привет! Встреча по проекту переносится на пятницу 15:00.\n"
                          "Подтверди, пожалуйста, что время подходит.\n\nИван"),
        Message(id="2", folder="INBOX", from_addr="billing@hosting.example", to=["you@example.com"],
                subject="Invoice #4211", date="2026-07-20 08:40", snippet="",
                unread=True,
                body_text="Hello,\n\nYour invoice #4211 for July hosting (24.00 EUR) is due "
                          "on 2026-07-28.\n\nBest regards,\nHosting Billing"),
        Message(id="3", folder="INBOX", from_addr="newsletter@osnews.example", to=["you@example.com"],
                subject="Weekly digest", date="2026-07-19 07:00", snippet="",
                unread=False,
                body_text="This week in open source: release notes, benchmarks, and a "
                          "long-read about local LLM desktops."),
    ])


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from .mail_view import run_mail_gtk
    from .gtk_view import gtk_available

    if not gtk_available():
        print(
            "kow-mail: PyGObject (gi) not available — the mail window needs GTK3.\n"
            "Install it via provisioning (kow_gui=true) or use the CLI: kow mail search …",
            file=sys.stderr,
        )
        return 2

    if args.demo:
        backend = demo_backend()
    else:
        from kowalski.config import Config
        from kowalski.mail import build_backend

        backend = build_backend(Config.load())
        if backend is None:
            print("kow-mail: KOW_MAIL_BACKEND=imap but the 'mail' extra isn't installed "
                  "(pip install 'kowalski[mail]').", file=sys.stderr)
            return 2

    client = OmniClient(socket_path=args.socket)
    return run_mail_gtk(backend, client)


if __name__ == "__main__":
    raise SystemExit(main())
