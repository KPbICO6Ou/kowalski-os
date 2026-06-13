"""memory.* and profile.* tools: long-term memory and user personalization."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..memory.embedder import Embedder
from ..memory.store import MemoryStore
from ..store import Store
from .base import RiskLevel, ToolDef, ToolResult


class RememberArgs(BaseModel):
    text: str = Field(min_length=3)
    tags: list[str] = Field(default_factory=list)


class RecallArgs(BaseModel):
    query: str
    limit: int = Field(default=5, ge=1, le=25)


class ForgetArgs(BaseModel):
    memory_id: int


class ProfileSetArgs(BaseModel):
    key: str = Field(min_length=1)
    value: str


class ProfileGetArgs(BaseModel):
    key: str | None = None


def build_memory_tools(store: Store, embedder: Embedder) -> list[ToolDef]:
    memory = MemoryStore(store)

    async def memory_remember(args: RememberArgs) -> ToolResult:
        note = ""
        try:
            embedding = await embedder.embed(args.text)
        except Exception as exc:
            embedding = []
            note = f" (stored without embedding: {exc})"
        memory_id = memory.remember(args.text, args.tags, embedding)
        return ToolResult(
            ok=True,
            content=f"Remembered #{memory_id}{note}.",
            data={"id": memory_id, "embedded": bool(embedding)},
        )

    async def memory_recall(args: RecallArgs) -> ToolResult:
        try:
            query_embedding = await embedder.embed(args.query)
        except Exception as exc:
            return ToolResult(ok=False, content=f"Could not embed query: {exc}")
        hits = memory.recall(query_embedding, args.limit)
        if not hits:
            return ToolResult(ok=True, content="No memories stored.", data=[])
        lines = [f"#{h['id']} (score {h['score']:.2f}): {h['text']}" for h in hits]
        return ToolResult(ok=True, content="\n".join(lines), data=hits)

    async def memory_forget(args: ForgetArgs) -> ToolResult:
        if memory.forget(args.memory_id):
            return ToolResult(ok=True, content=f"Forgot memory #{args.memory_id}.")
        return ToolResult(ok=False, content=f"No memory with id {args.memory_id}.")

    async def profile_set(args: ProfileSetArgs) -> ToolResult:
        memory.set_fact(args.key, args.value)
        return ToolResult(
            ok=True,
            content=f"Saved profile fact '{args.key}'.",
            data={"key": args.key, "value": args.value},
        )

    async def profile_get(args: ProfileGetArgs) -> ToolResult:
        if args.key is not None:
            value = memory.get_fact(args.key)
            if value is None:
                return ToolResult(ok=False, content=f"No profile fact '{args.key}'.")
            return ToolResult(
                ok=True, content=f"{args.key}: {value}", data={args.key: value}
            )
        facts = memory.all_facts()
        if not facts:
            return ToolResult(ok=True, content="No profile facts stored.", data={})
        lines = [f"{key}: {value}" for key, value in facts.items()]
        return ToolResult(ok=True, content="\n".join(lines), data=facts)

    return [
        ToolDef(
            name="memory.remember",
            description="Store a long-term memory (a fact or preference) for future recall.",
            args_model=RememberArgs,
            risk=RiskLevel.WRITE,
            handler=memory_remember,
        ),
        ToolDef(
            name="memory.recall",
            description="Search long-term memories most relevant to a query.",
            args_model=RecallArgs,
            risk=RiskLevel.READ,
            handler=memory_recall,
        ),
        ToolDef(
            name="memory.forget",
            description="Delete a long-term memory by its id.",
            args_model=ForgetArgs,
            risk=RiskLevel.WRITE,
            handler=memory_forget,
        ),
        ToolDef(
            name="profile.set",
            description="Set a user profile fact (key/value), e.g. name or preference.",
            args_model=ProfileSetArgs,
            risk=RiskLevel.WRITE,
            handler=profile_set,
        ),
        ToolDef(
            name="profile.get",
            description="Get one user profile fact by key, or all facts when no key is given.",
            args_model=ProfileGetArgs,
            risk=RiskLevel.READ,
            handler=profile_get,
        ),
    ]
