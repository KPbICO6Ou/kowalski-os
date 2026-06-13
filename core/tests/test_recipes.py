from pathlib import Path

import pytest
from pydantic import BaseModel, Field, ValidationError

from kowalski.journal import ActionJournal
from kowalski.policy import AutoConfirm, AutoDeny, SecurityPolicy
from kowalski.recipes.engine import RecipeEngine
from kowalski.recipes.model import (
    Recipe,
    Step,
    Trigger,
    dump_recipe_yaml,
    load_recipe_yaml,
)
from kowalski.recipes.store import RecipeStore
from kowalski.store import Store
from kowalski.tools.base import RiskLevel, ToolDef, ToolResult
from kowalski.tools.registry import ToolRegistry

GOOD_YAML = """
name: morning
description: a daily greeting
trigger:
  kind: interval
  every_seconds: 60
steps:
  - tool: producer.make
    args:
      seed: hello
  - tool: consumer.take
    args:
      value: "{{ steps.0.value }}"
"""


# -- model validation -------------------------------------------------------


def test_model_good_recipe():
    recipe = load_recipe_yaml(GOOD_YAML)
    assert recipe.name == "morning"
    assert recipe.trigger.kind == "interval"
    assert recipe.trigger.every_seconds == 60
    assert len(recipe.steps) == 2
    assert recipe.steps[1].args["value"] == "{{ steps.0.value }}"


def test_model_empty_steps_rejected():
    with pytest.raises(ValidationError):
        Recipe(name="x", trigger=Trigger(kind="manual"), steps=[])


def test_model_blank_name_rejected():
    with pytest.raises(ValidationError):
        Recipe(name="   ", trigger=Trigger(kind="manual"), steps=[Step(tool="t")])


def test_time_trigger_requires_at():
    with pytest.raises(ValidationError):
        Trigger(kind="time")
    Trigger(kind="time", at="2030-01-01T09:00:00")


def test_interval_trigger_requires_positive_seconds():
    with pytest.raises(ValidationError):
        Trigger(kind="interval")
    with pytest.raises(ValidationError):
        Trigger(kind="interval", every_seconds=0)
    Trigger(kind="interval", every_seconds=30)


def test_inotify_trigger_requires_path():
    with pytest.raises(ValidationError):
        Trigger(kind="inotify")
    Trigger(kind="inotify", path="/tmp/watch")


def test_load_rejects_non_mapping():
    with pytest.raises(ValueError):
        load_recipe_yaml("- just\n- a\n- list")


def test_yaml_round_trip():
    recipe = load_recipe_yaml(GOOD_YAML)
    text = dump_recipe_yaml(recipe)
    again = load_recipe_yaml(text)
    assert again == recipe
    # exclude_none drops unset trigger fields
    assert "at:" not in text
    assert "path:" not in text


# -- store ------------------------------------------------------------------


def test_store_save_get_list_remove(tmp_path: Path):
    store = RecipeStore(tmp_path / "recipes")
    recipe = load_recipe_yaml(GOOD_YAML)
    path = store.save(recipe)
    assert path.exists()
    assert store.get("morning") == recipe
    assert store.get("missing") is None
    names = [r.name for r in store.list()]
    assert names == ["morning"]
    assert store.remove("morning") is True
    assert store.remove("morning") is False
    assert store.list() == []


# -- engine -----------------------------------------------------------------


class ProducerArgs(BaseModel):
    seed: str


class ConsumerArgs(BaseModel):
    value: str = Field(min_length=1)


class WriteArgs(BaseModel):
    path: str


def _producer_consumer_tools(seen: list[str]) -> list[ToolDef]:
    async def producer(args: ProducerArgs) -> ToolResult:
        return ToolResult(ok=True, content="made", data={"value": args.seed.upper()})

    async def consumer(args: ConsumerArgs) -> ToolResult:
        seen.append(args.value)
        return ToolResult(ok=True, content=f"took {args.value}", data={"got": args.value})

    return [
        ToolDef(
            name="producer.make", description="make", args_model=ProducerArgs,
            risk=RiskLevel.READ, handler=producer,
        ),
        ToolDef(
            name="consumer.take", description="take", args_model=ConsumerArgs,
            risk=RiskLevel.READ, handler=consumer,
        ),
    ]


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture
def journal(store: Store) -> ActionJournal:
    return ActionJournal(store)


@pytest.fixture
def policy(tmp_path: Path) -> SecurityPolicy:
    return SecurityPolicy(allowed_paths=[tmp_path])


async def test_engine_runs_two_steps_with_template(
    tmp_path: Path, journal: ActionJournal, policy: SecurityPolicy
):
    registry = ToolRegistry(policy=policy, journal=journal, confirmer=AutoConfirm())
    seen: list[str] = []
    registry.register_all(_producer_consumer_tools(seen))

    recipe_store = RecipeStore(tmp_path / "recipes")
    recipe_store.save(load_recipe_yaml(GOOD_YAML))
    engine = RecipeEngine(recipe_store, registry)

    results = await engine.run("morning")

    assert [r["ok"] for r in results] == [True, True]
    # producer.make upper-cased "hello"; template threaded it to consumer.take
    assert seen == ["HELLO"]
    assert results[1]["content"] == "took HELLO"

    entries = journal.recent(5)
    tools = {e["tool"] for e in entries}
    assert {"producer.make", "consumer.take"} <= tools
    assert all(e["decision"] == "executed" for e in entries if e["tool"] in tools)


async def test_engine_denied_step_stops_chain(
    tmp_path: Path, journal: ActionJournal, policy: SecurityPolicy
):
    # AutoDeny confirmer: a WRITE tool writing outside the allowlist -> CONFIRM -> denied.
    registry = ToolRegistry(policy=policy, journal=journal, confirmer=AutoDeny())

    async def writer(args: WriteArgs) -> ToolResult:
        raise AssertionError("denied step must not execute its handler")

    async def after(args: ConsumerArgs) -> ToolResult:
        raise AssertionError("step after a denied step must not run")

    registry.register(ToolDef(
        name="danger.write", description="w", args_model=WriteArgs,
        risk=RiskLevel.WRITE, handler=writer, path_fields=("path",),
    ))
    registry.register(ToolDef(
        name="after.run", description="a", args_model=ConsumerArgs,
        risk=RiskLevel.READ, handler=after,
    ))

    recipe = Recipe(
        name="risky",
        trigger=Trigger(kind="manual"),
        steps=[
            Step(tool="danger.write", args={"path": "/somewhere/outside.txt"}),
            Step(tool="after.run", args={"value": "x"}),
        ],
    )
    recipe_store = RecipeStore(tmp_path / "recipes")
    recipe_store.save(recipe)
    engine = RecipeEngine(recipe_store, registry)

    results = await engine.run("risky")

    assert len(results) == 1  # chain stopped after the denied step
    assert results[0]["ok"] is False
    assert results[0]["stopped"] is True
    assert journal.recent(1)[0]["decision"] == "denied_by_user"


async def test_engine_unknown_recipe(tmp_path: Path, journal: ActionJournal, policy):
    registry = ToolRegistry(policy=policy, journal=journal, confirmer=AutoConfirm())
    engine = RecipeEngine(RecipeStore(tmp_path / "recipes"), registry)
    with pytest.raises(ValueError):
        await engine.run("nope")
