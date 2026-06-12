"""Paragraph-aware text chunking: ~1200 char chunks with ~200 char line-aligned overlap."""

from __future__ import annotations

import re

DEFAULT_MAX_CHARS = 1200
DEFAULT_OVERLAP = 200


def chunk_text(
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    """Split text into overlapping chunks, preferring paragraph and line boundaries.

    Blocks are capped at max_chars - overlap so a chunk (overlap tail + block)
    never exceeds max_chars. Empty chunks are dropped.
    """
    if not text.strip():
        return []
    # -1 leaves room for the newline that joins the overlap tail to the block
    block_limit = max(1, max_chars - overlap - 1)
    blocks = _blocks(text, block_limit)

    chunks: list[str] = []
    current = ""
    for block in blocks:
        if not current:
            current = block
            continue
        if len(current) + 2 + len(block) <= max_chars:
            current = f"{current}\n\n{block}"
            continue
        chunks.append(current)
        tail = _overlap_tail(current, overlap)
        current = f"{tail}\n{block}" if tail else block
    if current.strip():
        chunks.append(current)
    return [chunk for chunk in chunks if chunk.strip()]


def _blocks(text: str, limit: int) -> list[str]:
    """Paragraphs first; oversized paragraphs split by lines, oversized lines hard-split."""
    blocks: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip("\n")
        if not paragraph.strip():
            continue
        if len(paragraph) <= limit:
            blocks.append(paragraph)
            continue
        piece = ""
        for line in paragraph.splitlines():
            while len(line) > limit:  # pathological single line: hard split
                if piece:
                    blocks.append(piece)
                    piece = ""
                blocks.append(line[:limit])
                line = line[limit:]
            if not piece:
                piece = line
            elif len(piece) + 1 + len(line) <= limit:
                piece = f"{piece}\n{line}"
            else:
                blocks.append(piece)
                piece = line
        if piece.strip():
            blocks.append(piece)
    return blocks


def _overlap_tail(chunk: str, overlap: int) -> str:
    """Last ~overlap chars of a chunk, advanced to the next line start if one is in range."""
    if overlap <= 0 or len(chunk) <= overlap:
        return ""
    tail = chunk[-overlap:]
    newline = tail.find("\n")
    if newline != -1:
        tail = tail[newline + 1 :]
    return tail.strip("\n")
