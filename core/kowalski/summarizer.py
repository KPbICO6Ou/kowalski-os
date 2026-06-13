"""Conversation summarisation: compress old turns into a dense digest.

Used by `conversations.run_turn` to keep long conversations within a manageable
context window while preserving the facts the model still needs. The single LLM
call is tool-free and must never raise — on any failure we return an empty
string so the caller can fall back to plain history."""

from __future__ import annotations

from typing import Any

from .agent.llm import LLMClient

SUMMARY_SYSTEM_PROMPT = (
    "You are a conversation compressor. Compress the following conversation "
    "excerpt into a single dense paragraph. Preserve all facts, decisions, "
    "values, names, numbers, and filenames mentioned. Drop pleasantries and "
    "filler. Do not add information that is not present. Output only the "
    "summary paragraph, no preamble."
)


def _render_excerpt(messages: list[dict[str, Any]]) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


async def summarize_messages(llm: LLMClient, messages: list[dict[str, Any]]) -> str:
    """Compress `messages` into a dense paragraph via one tool-free LLM call.

    Returns the accumulated summary text, or "" on any error (never raises)."""
    if not messages:
        return ""
    try:
        chat_messages = [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": _render_excerpt(messages)},
        ]
        parts: list[str] = []
        async for chunk in llm.chat(chat_messages, []):
            if chunk.content_delta:
                parts.append(chunk.content_delta)
        return "".join(parts).strip()
    except Exception:
        return ""
