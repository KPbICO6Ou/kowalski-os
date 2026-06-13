from pathlib import Path

import pytest
from pydantic import BaseModel

from kowalski.journal import ActionJournal
from kowalski.policy import AutoConfirm, SecurityPolicy
from kowalski.recipes.engine import RecipeEngine
from kowalski.recipes.store import RecipeStore
from kowalski.store import Store
from kowalski.tools.base import RiskLevel, ToolDef, ToolResult
from kowalski.tools.recipes import build_recipe_tools
from kowalski.tools.registry import ToolRegistry

VALID_YAML = """
name: ping
description: trivial recipe
trigger:
  kind: manual
steps:
  - tool: test.ping
    args:
      label: hi
"""

INVALID_YAML = """
name: broken
trigger:
  kind: time
steps:
  - tool: test.ping
"""  # time trigger missing 'at'


class PingArgs(BaseModel):
    label: str


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture
def setup(tmp_path: Path, store: Store):
    journal = ActionJournal(store)
    policy = SecurityPolicy(allowed_paths=[tmp_path])
    registry = ToolRegistry(policy=policy, journal=journal, confirmer=AutoConfirm())

    async def ping(args: PingArgs) -> ToolResult:
        return ToolResult(ok=True, content=f"pong {args.label}", data={"label": args.label})

    registry.register(ToolDef(
        name="test.ping", description="ping", args_model=PingArgs,
        risk=RiskLevel.READ, handler=ping,
    ))

    recipe_store = RecipeStore(tmp_path / "recipes")
    engine = RecipeEngine(recipe_store, registry)
    tools = {t.name: t for t in build_recipe_tools(engine)}
    registry.register_all(list(tools.values()))
    return registry, recipe_store, tools


async def test_add_persists_and_lists(setup):
    registry, recipe_store, tools = setup
    res = await registry.execute("recipes.add", {"yaml": VALID_YAML})
    assert res.ok
    assert res.data["name"] == "ping"
    assert recipe_store.get("ping") is not None

    listed = await registry.execute("recipes.list", {})
    assert listed.ok
    names = [r["name"] for r in listed.data["recipes"]]
    assert names == ["ping"]


async def test_add_invalid_yaml_fails(setup):
    registry, recipe_store, tools = setup
    res = await registry.execute("recipes.add", {"yaml": INVALID_YAML})
    assert res.ok is False
    assert "Invalid recipe" in res.content
    assert recipe_store.get("broken") is None


async def test_run_executes_steps(setup):
    registry, recipe_store, tools = setup
    await registry.execute("recipes.add", {"yaml": VALID_YAML})
    res = await registry.execute("recipes.run", {"name": "ping"})
    assert res.ok
    assert res.data["steps"][0]["tool"] == "test.ping"
    assert res.data["steps"][0]["content"] == "pong hi"


async def test_run_unknown_recipe_fails(setup):
    registry, recipe_store, tools = setup
    res = await registry.execute("recipes.run", {"name": "ghost"})
    assert res.ok is False


async def test_remove_deletes(setup):
    registry, recipe_store, tools = setup
    await registry.execute("recipes.add", {"yaml": VALID_YAML})
    res = await registry.execute("recipes.remove", {"name": "ping"})
    assert res.ok
    assert recipe_store.get("ping") is None
    again = await registry.execute("recipes.remove", {"name": "ping"})
    assert again.ok is False
