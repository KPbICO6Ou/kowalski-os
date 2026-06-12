"""notes.* tools: quick notes stored in SQLite."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..store import Store
from .base import RiskLevel, ToolDef, ToolResult


class NoteCreateArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="")
    tags: list[str] = Field(default_factory=list)


def build_tools(store: Store) -> list[ToolDef]:
    async def notes_create(args: NoteCreateArgs) -> ToolResult:
        cur = store.conn.execute(
            "INSERT INTO notes (title, body, tags) VALUES (?, ?, ?)",
            (args.title, args.body, ",".join(args.tags)),
        )
        store.conn.commit()
        note_id = cur.lastrowid
        return ToolResult(
            ok=True, content=f"Note #{note_id} saved: {args.title}", data={"id": note_id}
        )

    return [
        ToolDef(
            name="notes.create",
            description="Save a note (title, body, optional tags).",
            args_model=NoteCreateArgs,
            risk=RiskLevel.WRITE,
            handler=notes_create,
        )
    ]
