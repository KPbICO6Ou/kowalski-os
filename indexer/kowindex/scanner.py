"""Filesystem scan: walk index roots, chunk + embed changed files, prune vanished ones."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .chunker import chunk_text
from .embedder import Embedder
from .store import VectorStore

TEXT_EXTENSIONS = {
    ".md", ".txt", ".rst", ".py", ".js", ".ts", ".tsx", ".json",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".sh", ".csv",
}
SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", "dist", "build"}
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB


@dataclass
class ScanSummary:
    scanned: int = 0
    indexed: int = 0
    skipped: int = 0
    deleted: int = 0
    chunks: int = 0

    def __str__(self) -> str:
        return (
            f"scanned={self.scanned} indexed={self.indexed} skipped={self.skipped}"
            f" deleted={self.deleted} chunks={self.chunks}"
        )


def is_eligible(path: Path) -> bool:
    """Indexable file: known text extension, or .pdf when pdftotext is on PATH."""
    if path.name.startswith("."):
        return False
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return True
    return suffix == ".pdf" and shutil.which("pdftotext") is not None


def read_text(path: Path) -> str | None:
    """File contents as text, or None for unreadable/oversized files."""
    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            return None
        if path.suffix.lower() == ".pdf":
            result = subprocess.run(
                ["pdftotext", "-q", str(path), "-"],
                capture_output=True,
                timeout=30,
                check=False,
            )
            if result.returncode != 0:
                return None
            return result.stdout.decode("utf-8", errors="replace")
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def iter_files(root: Path) -> Iterator[Path]:
    """Walk root, pruning hidden directories and the usual vendored/build trees."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS
        )
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if is_eligible(path):
                yield path


def index_file(path: Path, store: VectorStore, embedder: Embedder) -> int:
    """Chunk + embed one file and replace its rows; returns chunks stored (0 = skipped)."""
    stat = path.stat()
    if stat.st_size > MAX_FILE_SIZE:
        return 0
    text = read_text(path)
    if text is None:
        return 0
    texts = chunk_text(text)
    if not texts:
        return 0
    embeddings = embedder.embed(texts)
    return store.replace_file(str(path), stat.st_mtime, stat.st_size, texts, embeddings)


def scan(roots: Iterable[Path], store: VectorStore, embedder: Embedder) -> ScanSummary:
    """Incremental scan: skip unchanged (mtime+size), reindex changed, drop vanished."""
    summary = ScanSummary()
    roots = [Path(root).expanduser() for root in roots]
    known = store.all_files()
    seen: set[str] = set()

    for root in roots:
        if not root.is_dir():
            continue
        for path in iter_files(root):
            summary.scanned += 1
            key = str(path)
            seen.add(key)
            try:
                stat = path.stat()
            except OSError:
                summary.skipped += 1
                continue
            if known.get(key) == (stat.st_mtime, stat.st_size):
                summary.skipped += 1
                continue
            chunks = index_file(path, store, embedder)
            if chunks:
                summary.indexed += 1
                summary.chunks += chunks
            else:
                summary.skipped += 1

    prefixes = tuple(str(root) + os.sep for root in roots)
    for known_path in known:
        if known_path in seen or not known_path.startswith(prefixes):
            continue
        store.delete_file(known_path)
        summary.deleted += 1
    return summary


def update_paths(paths: Iterable[Path], store: VectorStore, embedder: Embedder) -> ScanSummary:
    """Incremental update for an explicit set of paths (used by the watcher)."""
    summary = ScanSummary()
    known = store.all_files()
    for path in paths:
        key = str(path)
        if not path.exists():
            if key in known:
                store.delete_file(key)
                summary.deleted += 1
            else:  # a removed directory: drop everything indexed beneath it
                prefix = key + os.sep
                for known_path in known:
                    if known_path.startswith(prefix):
                        store.delete_file(known_path)
                        summary.deleted += 1
            continue
        if not path.is_file() or not is_eligible(path):
            continue
        summary.scanned += 1
        stat = path.stat()
        if known.get(key) == (stat.st_mtime, stat.st_size):
            summary.skipped += 1
            continue
        chunks = index_file(path, store, embedder)
        if chunks:
            summary.indexed += 1
            summary.chunks += chunks
        else:
            summary.skipped += 1
    return summary
