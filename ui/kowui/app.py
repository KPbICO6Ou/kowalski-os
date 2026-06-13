"""kow-omni entry point.

Default mode tries the GTK3 omnibox window (needs PyGObject, typically Linux);
when `gi` is unavailable it prints a notice and falls back to the tty REPL.
`--cli` forces the REPL, `--socket PATH` overrides the daemon socket.

The Super+Space global hotkey is part of the XFCE integration (libkeybinder)
phase and is not bound by this entry point yet.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from . import __version__
from .client import DaemonUnavailableError, OmniClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kow-omni", description="Kowalski omnibox UI")
    parser.add_argument("--version", action="version", version=f"kow-omni {__version__}")
    parser.add_argument("--cli", action="store_true", help="run the terminal REPL instead of GTK")
    parser.add_argument("--socket", metavar="PATH", default=None, help="daemon socket path")
    return parser


def _run_cli(client: OmniClient) -> int:
    from .tty import run_cli

    try:
        return asyncio.run(run_cli(client))
    except DaemonUnavailableError as exc:
        print(f"kow-omni: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = OmniClient(socket_path=args.socket)

    if args.cli:
        return _run_cli(client)

    from .gtk_view import gtk_available, run_gtk

    if gtk_available():
        return run_gtk(client)
    print(
        "kow-omni: PyGObject (gi) not available — falling back to --cli mode. "
        "Install PyGObject + GTK3 on Linux for the omnibox window.",
        file=sys.stderr,
    )
    return _run_cli(client)


if __name__ == "__main__":
    raise SystemExit(main())
