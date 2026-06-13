from pydantic import BaseModel, Field

from kowalski.agent.events import (
    DoneEvent,
    PlanEvent,
    PlanStepEvent,
    ToolResultEvent,
)
from kowalski.agent.llm import ToolCall
from kowalski.agent.planner import Planner, _parse_plan
from kowalski.tools.base import RiskLevel, ToolDef, ToolResult

from .fake_llm import FakeLLM


class EchoArgs(BaseModel):
    text: str = Field(min_length=1)


async def echo_handler(args: EchoArgs) -> ToolResult:
    return ToolResult(ok=True, content=f"echo: {args.text}")


def add_echo(registry):
    registry.register(ToolDef(
        name="test.echo", description="echo", args_model=EchoArgs,
        risk=RiskLevel.READ, handler=echo_handler,
    ))


async def collect(planner: Planner, goal: str):
    return [event async for event in planner.run(goal)]


# --- make_plan parsing -----------------------------------------------------


async def test_make_plan_json_array(registry):
    planner = Planner(FakeLLM(['["do A", "do B", "do C"]']), registry)
    steps = await planner.make_plan("goal")
    assert steps == ["do A", "do B", "do C"]


async def test_make_plan_numbered_list_fallback(registry):
    script = ["1. first thing\n2. second thing\n3. third thing"]
    planner = Planner(FakeLLM(script), registry)
    steps = await planner.make_plan("goal")
    assert steps == ["first thing", "second thing", "third thing"]


async def test_make_plan_garbage_degenerates(registry):
    planner = Planner(FakeLLM(["I cannot help with that, sorry."]), registry)
    steps = await planner.make_plan("the original goal")
    assert steps == ["the original goal"]


async def test_make_plan_caps_at_eight(registry):
    array = "[" + ", ".join(f'"step {i}"' for i in range(12)) + "]"
    planner = Planner(FakeLLM([array]), registry)
    steps = await planner.make_plan("goal")
    assert len(steps) == 8


def test_parse_plan_json_inside_prose():
    text = 'Here is the plan: ["alpha", "beta"]. Hope that helps!'
    assert _parse_plan(text) == ["alpha", "beta"]


def test_parse_plan_bulleted():
    assert _parse_plan("- one\n- two") == ["one", "two"]


# --- run() end to end ------------------------------------------------------


async def test_run_two_step_plan_no_tools(registry):
    llm = FakeLLM(['["do A", "do B"]', "Did A.", "Did B.", "Final summary."])
    events = await collect(Planner(llm, registry), "the goal")

    plan_events = [e for e in events if isinstance(e, PlanEvent)]
    assert len(plan_events) == 1
    assert plan_events[0].steps == ["do A", "do B"]

    starts = [e for e in events if isinstance(e, PlanStepEvent) and e.status == "start"]
    dones = [e for e in events if isinstance(e, PlanStepEvent) and e.status == "done"]
    assert [e.index for e in starts] == [0, 1]
    assert [e.index for e in dones] == [0, 1]

    done = [e for e in events if isinstance(e, DoneEvent)]
    assert len(done) == 1
    assert "Final summary." in done[0].answer


async def test_run_threads_history(registry):
    llm = FakeLLM(['["do A", "do B"]', "Did A.", "Did B.", "Final summary."])
    await collect(Planner(llm, registry), "the goal")

    # llm.calls: [0]=make_plan, [1]=step A, [2]=step B, [3]=synthesis.
    # Step B's messages must include step A's assistant answer.
    step_b_messages = llm.calls[2]
    assert any(
        m["role"] == "assistant" and "Did A." in m["content"] for m in step_b_messages
    )
    synthesis_messages = llm.calls[3]
    assert any(
        m["role"] == "assistant" and "Did B." in m["content"] for m in synthesis_messages
    )


async def test_run_step_with_tool(registry):
    add_echo(registry)
    llm = FakeLLM([
        '["use the tool"]',
        [ToolCall(name="test.echo", args={"text": "ping"})],
        "Tool returned ping.",
        "All done.",
    ])
    events = await collect(Planner(llm, registry), "the goal")

    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert tool_results and tool_results[0].ok
    assert "echo: ping" in tool_results[0].content

    done = [e for e in events if isinstance(e, DoneEvent)]
    assert len(done) == 1 and "All done." in done[0].answer
