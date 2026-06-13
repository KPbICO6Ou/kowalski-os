"""Hybrid file search (files.find) and conversation search (conversations.search).

``files.find`` merges up to three independent sources into one ranked, deduped
list keyed by absolute path:

  a. **name**     — substring/glob match on file names (fd -> pure-python walk),
                    reused from ``files.py``; the most precise signal.
  b. **content**  — ``ripgrep`` files-with-matches scan (skipped if rg is absent),
                    with a cheap matching-line snippet.
  c. **semantic** — kow-index embedding search (skipped if the index/package is
                    unavailable or empty).

Each source is best-effort: a failure in one is logged and ignored so the tool
still returns whatever the others produced.

``conversations.search`` is a thin formatter over ``ConversationSearch``.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from ..config import Config
from ..convsearch import ConversationSearch
from ..store import Store
from .base import RiskLevel, ToolDef, ToolResult
from .files import _fd_search, _python_walk

log = logging.getLogger(__name__)

# Per-source weights: name is the most precise, semantic the fuzziest.
WEIGHT_NAME = 1.0
WEIGHT_CONTENT = 0.6
WEIGHT_SEMANTIC = 0.5
RG_MAX_COUNT = 1  # we only need to know a file matches + one snippet line


class FileFindArgs(BaseModel):
    query: str = Field(
        min_length=2,
        description="Natural-language phrase or keywords; matched against file "
        "names, file contents, and the semantic index.",
    )
    root: str | None = Field(default=None, description="Directory to search in (default: home)")
    limit: int = Field(default=10, ge=1, le=50)


class _Hit:
    __slots__ = ("path", "score", "sources", "snippet")

    def __init__(self, path: str):
        self.path = path
        self.score = 0.0
        self.sources: list[str] = []
        self.snippet: str | None = None

    def add(self, source: str, score: float, snippet: str | None = None) -> None:
        self.score += score
        if source not in self.sources:
            self.sources.append(source)
        if snippet and not self.snippet:
            self.snippet = snippet


async def _name_source(query: str, root: Path, limit: int) -> list[str]:
    """File-name matches (fd if available, else pure-python walk)."""
    pattern = query if any(c in query for c in "*?[") else f"*{query}*"
    if shutil.which("fd"):
        return await _fd_search(query, root, limit, None)
    return await asyncio.get_running_loop().run_in_executor(
        None, _python_walk, pattern, root, limit, None
    )


async def _content_source(query: str, root: Path, limit: int) -> list[tuple[str, str | None]]:
    """ripgrep files-with-matches; returns (path, snippet) pairs.

    Uses ``--files-with-matches`` for the path list and a second cheap
    ``--max-count 1`` pass to grab one matching line per file as a snippet.
    Returns an empty list (not an error) when rg is absent.
    """
    if not shutil.which("rg"):
        return []
    # First: the matching file paths.
    cmd = [
        "rg",
        "--files-with-matches",
        "--max-count",
        str(RG_MAX_COUNT),
        "--fixed-strings",
        "--smart-case",
        "--",
        query,
        str(root),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    stdout, _ = await proc.communicate()
    paths = [line for line in stdout.decode(errors="replace").splitlines() if line][:limit]

    results: list[tuple[str, str | None]] = []
    for path in paths:
        snippet = await _rg_snippet(query, path)
        results.append((path, snippet))
    return results


async def _rg_snippet(query: str, path: str) -> str | None:
    """One matching line from ``path`` (cheap; capped at one line)."""
    cmd = [
        "rg",
        "--no-line-number",
        "--no-filename",
        "--max-count",
        "1",
        "--fixed-strings",
        "--smart-case",
        "--",
        query,
        path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await proc.communicate()
    except OSError:
        return None
    line = stdout.decode(errors="replace").splitlines()
    if not line:
        return None
    text = " ".join(line[0].split())
    return text[:199] + "…" if len(text) > 200 else text


def _semantic_source(config: Config, query: str, limit: int) -> list[tuple[str, float, str | None]]:
    """kow-index semantic hits as (path, score, snippet); [] if unavailable/empty."""
    try:
        from kowindex.api import SemanticIndex
    except ImportError:
        return []
    try:
        db_path = config.get_path("KOW_INDEX_DB")
    except KeyError:
        return []
    if not db_path.exists():
        return []
    try:
        index = SemanticIndex(
            db_path,
            ollama_host=config.get("OLLAMA_HOST"),
            model=config.get("KOW_EMBED_MODEL"),
        )
        if not index.stats().get("chunks", 0):
            return []
        hits = index.search(query, limit)
    except Exception as exc:  # index down/corrupt/Ollama unreachable
        log.warning("files.find semantic source failed: %s", exc)
        return []
    return [(hit.path, float(hit.score), getattr(hit, "snippet", None)) for hit in hits]


def build_search_tools(config: Config) -> list[ToolDef]:
    """Factory for the hybrid ``files.find`` tool."""
    allowed_paths = config.allowed_paths

    async def files_find(args: FileFindArgs) -> ToolResult:
        root = Path(args.root).expanduser().resolve() if args.root else Path.home()
        if not any(root.is_relative_to(p) for p in allowed_paths):
            return ToolResult(ok=False, content=f"Search root {root} is outside allowed paths.")
        if not root.is_dir():
            return ToolResult(ok=False, content=f"Not a directory: {root}")

        # Fan out; oversample per source so the merge has material to rank.
        source_limit = min(args.limit * 3, 50)
        hits: dict[str, _Hit] = {}

        def _hit(path: str) -> _Hit:
            abspath = str(Path(path).expanduser().resolve())
            return hits.setdefault(abspath, _Hit(abspath))

        # a. name
        try:
            for path in await _name_source(args.query, root, source_limit):
                _hit(path).add("name", WEIGHT_NAME)
        except Exception as exc:
            log.warning("files.find name source failed: %s", exc)

        # b. content (ripgrep)
        try:
            for path, snippet in await _content_source(args.query, root, source_limit):
                _hit(path).add("content", WEIGHT_CONTENT, snippet)
        except Exception as exc:
            log.warning("files.find content source failed: %s", exc)

        # c. semantic (only paths under root are kept)
        try:
            sem = await asyncio.get_running_loop().run_in_executor(
                None, _semantic_source, config, args.query, source_limit
            )
            for path, score, snippet in sem:
                resolved = Path(path).expanduser().resolve()
                if not resolved.is_relative_to(root):
                    continue
                _hit(str(resolved)).add("semantic", WEIGHT_SEMANTIC * score, snippet)
        except Exception as exc:
            log.warning("files.find semantic source failed: %s", exc)

        if not hits:
            return ToolResult(ok=True, content="No matches found.", data=[])

        ranked = sorted(hits.values(), key=lambda h: h.score, reverse=True)[: args.limit]
        data = [
            {
                "path": h.path,
                "score": round(h.score, 4),
                "sources": h.sources,
                **({"snippet": h.snippet} if h.snippet else {}),
            }
            for h in ranked
        ]
        lines = []
        for h in ranked:
            tail = f"  — {h.snippet}" if h.snippet else ""
            lines.append(f"score={h.score:.2f}  [{'+'.join(h.sources)}]  {h.path}{tail}")
        listing = "\n".join(lines)
        return ToolResult(
            ok=True,
            content=f"Top {len(ranked)} matches (best first):\n{listing}",
            data=data,
        )

    return [
        ToolDef(
            name="files.find",
            description=(
                "Hybrid file search: matches a natural-language query or keywords "
                "against file names, file contents (ripgrep), and the semantic "
                "index, then merges and ranks the results. Use this as the default "
                "way to locate files when the exact name is unknown."
            ),
            args_model=FileFindArgs,
            risk=RiskLevel.READ,
            handler=files_find,
            path_fields=("root",),
        )
    ]


class ConversationSearchArgs(BaseModel):
    query: str = Field(
        min_length=2, description="Substring to look for in past chat messages."
    )
    limit: int = Field(default=10, ge=1, le=50)


def build_conversation_search_tools(store: Store) -> list[ToolDef]:
    """Factory for the ``conversations.search`` tool."""
    searcher = ConversationSearch(store)

    async def conversations_search(args: ConversationSearchArgs) -> ToolResult:
        matches = searcher.search(args.query, args.limit)
        if not matches:
            return ToolResult(ok=True, content="No matching messages found.", data=[])
        lines = []
        for m in matches:
            title = m["title"] or "(untitled)"
            lines.append(f"{m['ts']}  [{m['role']}] {title}: {m['snippet']}")
        listing = "\n".join(lines)
        return ToolResult(
            ok=True,
            content=f"Found {len(matches)} matching messages (newest first):\n{listing}",
            data=matches,
        )

    return [
        ToolDef(
            name="conversations.search",
            description=(
                "Search past conversations: find chat messages whose text contains "
                "the query (newest first). Returns the conversation title, role, "
                "timestamp, and a snippet."
            ),
            args_model=ConversationSearchArgs,
            risk=RiskLevel.READ,
            handler=conversations_search,
        )
    ]
