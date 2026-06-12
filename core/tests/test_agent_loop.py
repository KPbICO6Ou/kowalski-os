from pydantic import BaseModel, Field

from kowalski.agent.events import DoneEvent, ErrorEvent, TokenEvent, ToolResultEvent
from kowalski.agent.llm import ToolCall
from kowalski.agent.loop import AgentLoop
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


async def collect(loop: AgentLoop, prompt: str):
    return [event async for event in loop.run(prompt)]


async def test_plain_answer_no_tools(registry):
    llm = FakeLLM(["The answer is 42."])
    events = await collect(AgentLoop(llm, registry), "question")
    assert any(isinstance(e, TokenEvent) for e in events)
    done = [e for e in events if isinstance(e, DoneEvent)]
    assert done and "42" in done[0].answer


async def test_tool_call_then_answer(registry):
    add_echo(registry)
    llm = FakeLLM([
        [ToolCall(name="test.echo", args={"text": "ping"})],
        "Tool said ping.",
    ])
    events = await collect(AgentLoop(llm, registry), "go")
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert tool_results and tool_results[0].ok
    assert isinstance(events[-1], DoneEvent)
    # the tool result was fed back to the LLM
    assert any(m["role"] == "tool" and "echo: ping" in m["content"] for m in llm.calls[1])


async def test_invalid_args_retry_then_success(registry):
    add_echo(registry)
    llm = FakeLLM([
        [ToolCall(name="test.echo", args={"bad": "field"})],
        [ToolCall(name="test.echo", args={"text": "fixed"})],
        "Done.",
    ])
    events = await collect(AgentLoop(llm, registry), "go")
    assert isinstance(events[-1], DoneEvent)
    # retry message contained the schema
    retry_msgs = [m for m in llm.calls[1] if m["role"] == "tool"]
    assert retry_msgs and "Expected schema" in retry_msgs[-1]["content"]


async def test_unknown_tool_retry(registry):
    add_echo(registry)
    llm = FakeLLM([
        [ToolCall(name="test.missing", args={})],
        "Recovered.",
    ])
    events = await collect(AgentLoop(llm, registry), "go")
    assert isinstance(events[-1], DoneEvent)
    retry_msgs = [m for m in llm.calls[1] if m["role"] == "tool"]
    assert "unknown tool" in retry_msgs[-1]["content"]
    assert "test.echo" in retry_msgs[-1]["content"]  # available tools listed


async def test_invalid_streak_aborts(registry):
    add_echo(registry)
    llm = FakeLLM([
        [ToolCall(name="test.echo", args={"bad": 1})],
        [ToolCall(name="test.echo", args={"bad": 2})],
        [ToolCall(name="test.echo", args={"bad": 3})],
        "never reached",
    ])
    events = await collect(AgentLoop(llm, registry), "go")
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert errors and "invalid tool calls" in errors[0].message


async def test_max_iterations_guard(registry):
    add_echo(registry)
    llm = FakeLLM([[ToolCall(name="test.echo", args={"text": "loop"})] for _ in range(10)])
    events = await collect(AgentLoop(llm, registry, max_iterations=3), "go")
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert errors and "max iterations" in errors[0].message


async def test_denied_tool_keeps_loop_running(deny_registry):
    class WriteArgs(BaseModel):
        path: str

    async def write_handler(args) -> ToolResult:
        return ToolResult(ok=True, content="written")

    deny_registry.register(ToolDef(
        name="test.write", description="w", args_model=WriteArgs,
        risk=RiskLevel.WRITE, handler=write_handler, path_fields=("path",),
    ))
    llm = FakeLLM([
        [ToolCall(name="test.write", args={"path": "/somewhere/else.txt"})],
        "Could not write, sorry.",
    ])
    events = await collect(AgentLoop(llm, deny_registry), "go")
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert tool_results and not tool_results[0].ok
    assert isinstance(events[-1], DoneEvent)
