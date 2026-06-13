import pytest
from pydantic import ValidationError

from kowalski.memory.embedder import MockEmbedder
from kowalski.tools.memory import (
    ForgetArgs,
    ProfileGetArgs,
    ProfileSetArgs,
    RecallArgs,
    RememberArgs,
    build_memory_tools,
)


class BrokenEmbedder:
    async def embed(self, text: str):
        raise RuntimeError("ollama down")


def tool(tools, name):
    return next(t for t in tools if t.name == name)


def test_remember_min_length():
    with pytest.raises(ValidationError):
        RememberArgs(text="hi")


def test_recall_limit_bounds():
    with pytest.raises(ValidationError):
        RecallArgs(query="x", limit=0)
    with pytest.raises(ValidationError):
        RecallArgs(query="x", limit=26)


async def test_remember_then_recall(tmp_store):
    tools = build_memory_tools(tmp_store, MockEmbedder())
    remember = tool(tools, "memory.remember")
    recall = tool(tools, "memory.recall")

    res = await remember.handler(RememberArgs(text="I love python", tags=["pref"]))
    assert res.ok
    assert res.data["embedded"] is True
    mem_id = res.data["id"]

    res = await recall.handler(RecallArgs(query="python language", limit=5))
    assert res.ok
    assert res.data[0]["id"] == mem_id
    assert f"#{mem_id}" in res.content


async def test_remember_without_embedding_on_failure(tmp_store):
    tools = build_memory_tools(tmp_store, BrokenEmbedder())
    remember = tool(tools, "memory.remember")
    res = await remember.handler(RememberArgs(text="stored anyway"))
    assert res.ok
    assert res.data["embedded"] is False
    assert "without embedding" in res.content


async def test_forget_tool(tmp_store):
    tools = build_memory_tools(tmp_store, MockEmbedder())
    remember = tool(tools, "memory.remember")
    forget = tool(tools, "memory.forget")
    res = await remember.handler(RememberArgs(text="forget me"))
    mem_id = res.data["id"]

    ok = await forget.handler(ForgetArgs(memory_id=mem_id))
    assert ok.ok
    missing = await forget.handler(ForgetArgs(memory_id=mem_id))
    assert not missing.ok


async def test_profile_set_get_all(tmp_store):
    tools = build_memory_tools(tmp_store, MockEmbedder())
    pset = tool(tools, "profile.set")
    pget = tool(tools, "profile.get")

    await pset.handler(ProfileSetArgs(key="name", value="Sam"))
    await pset.handler(ProfileSetArgs(key="color", value="blue"))

    one = await pget.handler(ProfileGetArgs(key="name"))
    assert one.ok and one.data == {"name": "Sam"}

    missing = await pget.handler(ProfileGetArgs(key="absent"))
    assert not missing.ok

    allf = await pget.handler(ProfileGetArgs())
    assert allf.ok and allf.data == {"color": "blue", "name": "Sam"}


async def test_recall_empty(tmp_store):
    tools = build_memory_tools(tmp_store, MockEmbedder())
    recall = tool(tools, "memory.recall")
    res = await recall.handler(RecallArgs(query="anything"))
    assert res.ok and res.data == []
