"""files.* tools: search by name (fd -> plocate -> pure-python walk) and by meaning
(semantic search over the kow-index embedding database)."""

from __future__ import annotations

import asyncio
import fnmatch
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from ..config import Config
from .base import RiskLevel, ToolDef, ToolResult

WALK_TIME_BUDGET = 10.0  # seconds, hard cap for the pure-python fallback


class FileSearchArgs(BaseModel):
    pattern: str = Field(description="File name pattern: substring or glob like *.pdf")
    root: str | None = Field(default=None, description="Directory to search in (default: home)")
    limit: int = Field(default=20, ge=1, le=100)
    modified_within_days: int | None = Field(
        default=None, description="Only files modified in the last N days"
    )


def _make_search_handler(allowed_paths: list[Path]):
    async def files_search(args: FileSearchArgs) -> ToolResult:
        root = Path(args.root).expanduser().resolve() if args.root else Path.home()
        if not any(root.is_relative_to(p) for p in allowed_paths):
            return ToolResult(ok=False, content=f"Search root {root} is outside allowed paths.")
        if not root.is_dir():
            return ToolResult(ok=False, content=f"Not a directory: {root}")

        pattern = args.pattern if any(c in args.pattern for c in "*?[") else f"*{args.pattern}*"

        if shutil.which("fd"):
            results = await _fd_search(args.pattern, root, args.limit, args.modified_within_days)
        else:
            results = await asyncio.get_running_loop().run_in_executor(
                None, _python_walk, pattern, root, args.limit, args.modified_within_days
            )

        if not results:
            return ToolResult(ok=True, content="No files found.", data=[])
        listing = "\n".join(results)
        return ToolResult(ok=True, content=f"Found {len(results)} files:\n{listing}", data=results)

    return files_search


async def _fd_search(
    pattern: str, root: Path, limit: int, modified_days: int | None
) -> list[str]:
    cmd = ["fd", "--max-results", str(limit), "--type", "f"]
    if any(c in pattern for c in "*?["):
        cmd += ["--glob", pattern]
    else:
        cmd += [pattern]
    if modified_days:
        cmd += ["--changed-within", f"{modified_days}d"]
    cmd += [str(root)]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    stdout, _ = await proc.communicate()
    return [line for line in stdout.decode().splitlines() if line][:limit]


def _python_walk(
    pattern: str, root: Path, limit: int, modified_days: int | None
) -> list[str]:
    results: list[str] = []
    deadline = time.monotonic() + WALK_TIME_BUDGET
    cutoff = (
        (datetime.now() - timedelta(days=modified_days)).timestamp() if modified_days else None
    )
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if time.monotonic() > deadline:
            break
        for filename in filenames:
            if fnmatch.fnmatch(filename.lower(), pattern.lower()):
                full = os.path.join(dirpath, filename)
                if cutoff is not None:
                    try:
                        if os.stat(full).st_mtime < cutoff:
                            continue
                    except OSError:
                        continue
                results.append(full)
                if len(results) >= limit:
                    return results
    return results


class SemanticSearchArgs(BaseModel):
    query: str = Field(
        min_length=2,
        description="Natural-language query; matches file content by meaning, not exact words",
    )
    limit: int = Field(default=8, ge=1, le=25)


def build_semantic_tools(config: Config) -> list[ToolDef]:
    async def files_search_semantic(args: SemanticSearchArgs) -> ToolResult:
        try:
            from kowindex.api import SemanticIndex
        except ImportError:
            return ToolResult(
                ok=False, content="semantic index not installed — pip install -e indexer"
            )

        db_path = config.get_path("KOW_INDEX_DB")
        if not db_path.exists():
            return ToolResult(
                ok=True,
                content=(
                    "The semantic index is empty — nothing has been indexed yet. "
                    "Ask the user to run `kow-index index` first."
                ),
                data=[],
            )
        index = SemanticIndex(
            db_path,
            ollama_host=config.get("OLLAMA_HOST"),
            model=config.get("KOW_EMBED_MODEL"),
        )
        try:
            if not index.stats().get("chunks", 0):
                return ToolResult(
                    ok=True,
                    content=(
                        "The semantic index is empty — nothing has been indexed yet. "
                        "Ask the user to run `kow-index index` first."
                    ),
                    data=[],
                )
            hits = index.search(args.query, args.limit)
        except Exception as exc:  # e.g. Ollama down, corrupt index
            return ToolResult(ok=False, content=f"semantic search failed: {exc}")

        if not hits:
            return ToolResult(ok=True, content="No semantic matches found.", data=[])
        lines = [f"score={hit.score:.2f}  {hit.path}  — {hit.snippet}" for hit in hits]
        data = [
            {
                "path": hit.path,
                "score": hit.score,
                "snippet": hit.snippet,
                "chunk_index": hit.chunk_index,
                "mtime": hit.mtime,
            }
            for hit in hits
        ]
        listing = "\n".join(lines)
        return ToolResult(
            ok=True,
            content=f"Top {len(hits)} semantic matches (best first):\n{listing}",
            data=data,
        )

    return [
        ToolDef(
            name="files.search_semantic",
            description=(
                "Search file contents by meaning: a natural-language query is matched "
                "against the semantic (embedding) index built by kow-index. Use it when "
                "the exact file name or wording is unknown."
            ),
            args_model=SemanticSearchArgs,
            risk=RiskLevel.READ,
            handler=files_search_semantic,
        )
    ]


def build_tools(allowed_paths: list[Path]) -> list[ToolDef]:
    return [
        ToolDef(
            name="files.search_by_name",
            description=(
                "Search for files by name (substring or glob pattern), optionally filtered "
                "by modification time. Returns full paths."
            ),
            args_model=FileSearchArgs,
            risk=RiskLevel.READ,
            handler=_make_search_handler(allowed_paths),
            path_fields=("root",),
        )
    ]
