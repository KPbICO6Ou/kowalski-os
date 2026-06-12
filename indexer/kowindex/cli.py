"""kow-index CLI: index roots, search the index, watch for changes, show status."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kowalski.config import Config

from . import __version__, settings
from .embedder import Embedder, OllamaEmbedder
from .store import VectorStore

DIM = "\033[2m"
RESET = "\033[0m"


def main(argv: list[str] | None = None, embedder: Embedder | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kow-index", description="Kowalski OS semantic indexer")
    parser.add_argument("--version", action="version", version=f"kow-index {__version__}")
    sub = parser.add_subparsers(dest="command")

    index = sub.add_parser("index", help="scan and (re)index the configured roots")
    index.add_argument("--paths", help="colon-separated roots (overrides KOW_INDEX_PATHS)")

    search = sub.add_parser("search", help="semantic search over the index")
    search.add_argument("query", help="what to look for")
    search.add_argument("-n", type=int, default=10, dest="limit", help="max results")

    watch = sub.add_parser("watch", help="index, then keep the index fresh via watchdog")
    watch.add_argument("--paths", help="colon-separated roots (overrides KOW_INDEX_PATHS)")

    sub.add_parser("status", help="index statistics and backend")

    args = parser.parse_args(argv)
    config = Config.load()

    if args.command == "index":
        return cmd_index(args, config, embedder)
    if args.command == "search":
        return cmd_search(args, config, embedder)
    if args.command == "watch":
        return cmd_watch(args, config, embedder)
    if args.command == "status":
        return cmd_status(config)
    parser.print_help()
    return 1


def _resolve_roots(args, config: Config) -> list[Path]:
    if getattr(args, "paths", None):
        return [Path(p).expanduser() for p in args.paths.split(":") if p]
    return settings.index_paths(config)


def _build_embedder(config: Config, embedder: Embedder | None) -> Embedder:
    if embedder is not None:
        return embedder
    return OllamaEmbedder(settings.ollama_host(config), settings.embed_model(config))


def _open_store_for_write(config: Config, embedder: Embedder) -> VectorStore:
    # Fake embedders advertise their dimension; nomic-embed-text is 768.
    dim = getattr(embedder, "dim", None)
    return VectorStore(settings.db_path(config), dim=dim)


def cmd_index(args, config: Config, embedder: Embedder | None) -> int:
    from .scanner import scan

    roots = _resolve_roots(args, config)
    active = _build_embedder(config, embedder)
    store = _open_store_for_write(config, active)
    try:
        summary = scan(roots, store, active)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()
    print(summary)
    return 0


def cmd_search(args, config: Config, embedder: Embedder | None) -> int:
    from .api import SemanticIndex

    index = SemanticIndex(
        settings.db_path(config),
        ollama_host=settings.ollama_host(config),
        model=settings.embed_model(config),
        embedder=embedder,
    )
    try:
        hits = index.search(args.query, limit=args.limit)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        index.close()
    if not hits:
        print("no results (is the index built? try: kow-index index)")
        return 0
    for hit in hits:
        print(f"{hit.score:.3f}  {hit.path} #{hit.chunk_index}")
        print(f"{DIM}      {hit.snippet}{RESET}")
    return 0


def cmd_watch(args, config: Config, embedder: Embedder | None) -> int:
    from .scanner import scan
    from .watcher import Watcher

    roots = _resolve_roots(args, config)
    active = _build_embedder(config, embedder)
    store = _open_store_for_write(config, active)
    try:
        summary = scan(roots, store, active)
        print(f"initial scan: {summary}")
        print(f"watching {':'.join(str(r) for r in roots)} (Ctrl-C to stop)")
        Watcher(roots, store, active).run()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()
    return 0


def cmd_status(config: Config) -> int:
    from .api import SemanticIndex

    index = SemanticIndex(
        settings.db_path(config),
        ollama_host=settings.ollama_host(config),
        model=settings.embed_model(config),
    )
    try:
        for key, value in index.stats().items():
            print(f"{key:<12} {value}")
    finally:
        index.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
