import pytest
from pydantic import ValidationError

from kowalski.tools.base import RiskLevel
from kowalski.tools.checklist import (
    PlanCreateArgs,
    PlanShowArgs,
    PlanUpdateArgs,
    build_checklist_tools,
)


def tool(name: str):
    return next(t for t in build_checklist_tools() if t.name == name)


def tools_by_name():
    return {t.name: t for t in build_checklist_tools()}


async def test_create_renders_steps_with_counts():
    create = tool("plan.create")
    result = await create.handler(PlanCreateArgs(steps=["a", "b", "c"]))
    assert result.ok
    assert "(0/3 done)" in result.content
    assert "☐ 1. a" in result.content
    assert "☐ 3. c" in result.content
    assert result.data["total"] == 3


async def test_update_marks_doing_then_done():
    tools = tools_by_name()
    create, update = tools["plan.create"], tools["plan.update"]
    await create.handler(PlanCreateArgs(steps=["first", "second"]))

    res = await update.handler(PlanUpdateArgs(step=1, status="doing"))
    assert res.ok
    assert "▶ 1. first" in res.content
    assert "(0/2 done)" in res.content

    res = await update.handler(PlanUpdateArgs(step=1, status="done"))
    assert res.ok
    assert "✓ 1. first" in res.content
    assert "(1/2 done)" in res.content


async def test_show_returns_current_state():
    tools = tools_by_name()
    await tools["plan.create"].handler(PlanCreateArgs(steps=["x", "y"]))
    await tools["plan.update"].handler(PlanUpdateArgs(step=2, status="done"))
    res = await tools["plan.show"].handler(PlanShowArgs())
    assert res.ok
    assert "(1/2 done)" in res.content
    assert "✓ 2. y" in res.content


async def test_show_empty_checklist():
    res = await tool("plan.show").handler(PlanShowArgs())
    assert res.ok
    assert res.content == "(no checklist yet)"


async def test_update_out_of_range_returns_error_result():
    tools = tools_by_name()
    await tools["plan.create"].handler(PlanCreateArgs(steps=["only one"]))
    res = await tools["plan.update"].handler(PlanUpdateArgs(step=5, status="done"))
    assert not res.ok
    assert "No step 5" in res.content
    # state untouched
    assert "☐ 1. only one" in res.content


def test_create_requires_at_least_one_step():
    with pytest.raises(ValidationError):
        PlanCreateArgs(steps=[])


def test_update_rejects_bad_status():
    with pytest.raises(ValidationError):
        PlanUpdateArgs(step=1, status="finished")


def test_update_rejects_non_positive_step():
    with pytest.raises(ValidationError):
        PlanUpdateArgs(step=0, status="todo")


async def test_separate_factories_have_independent_state():
    a = next(t for t in build_checklist_tools() if t.name == "plan.create")
    b_show = next(t for t in build_checklist_tools() if t.name == "plan.show")
    await a.handler(PlanCreateArgs(steps=["in a"]))
    res = await b_show.handler(PlanShowArgs())
    assert res.content == "(no checklist yet)"


def test_all_tools_are_read_risk():
    for t in build_checklist_tools():
        assert t.risk == RiskLevel.READ
