import asyncio

import pytest
from pydantic import BaseModel, Field

from kowalski.policy import ConfirmRequest
from kowalski.tools.base import (
    InvalidToolArgsError,
    RiskLevel,
    ToolDef,
    ToolResult,
    UnknownToolError,
)


class EchoArgs(BaseModel):
    text: str = Field(min_length=1)


async def echo_handler(args: EchoArgs) -> ToolResult:
    return ToolResult(ok=True, content=f"echo: {args.text}")


ECHO = ToolDef(
    name="test.echo", description="echo", args_model=EchoArgs,
    risk=RiskLevel.READ, handler=echo_handler,
)


class WriteArgs(BaseModel):
    path: str


async def write_handler(args: WriteArgs) -> ToolResult:
    return ToolResult(ok=True, content="written")


WRITE_TOOL = ToolDef(
    name="test.write", description="write", args_model=WriteArgs,
    risk=RiskLevel.WRITE, handler=write_handler, path_fields=("path",),
)


def test_duplicate_registration_rejected(registry):
    registry.register(ECHO)
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(ECHO)


def test_schemas_for_ollama(registry):
    registry.register(ECHO)
    schemas = registry.schemas_for_ollama()
    assert schemas[0]["function"]["name"] == "test.echo"
    assert "text" in schemas[0]["function"]["parameters"]["properties"]


async def test_execute_success_journaled(registry, journal):
    registry.register(ECHO)
    result = await registry.execute("test.echo", {"text": "hi"})
    assert result.ok and result.content == "echo: hi"
    entry = journal.recent(1)[0]
    assert entry["tool"] == "test.echo"
    assert entry["decision"] == "executed"
    assert entry["result_ok"] == 1


async def test_unknown_tool_raises_and_journals(registry, journal):
    with pytest.raises(UnknownToolError):
        await registry.execute("nope.nothing", {})
    assert journal.recent(1)[0]["decision"] == "unknown_tool"


async def test_invalid_args_raises_and_journals(registry, journal):
    registry.register(ECHO)
    with pytest.raises(InvalidToolArgsError) as exc_info:
        await registry.execute("test.echo", {"wrong": 1})
    assert "text" in str(exc_info.value.schema)
    assert journal.recent(1)[0]["decision"] == "invalid_args"


async def test_user_denial_journaled(deny_registry, journal, tmp_path):
    deny_registry.register(WRITE_TOOL)
    result = await deny_registry.execute("test.write", {"path": "/tmp/outside.txt"})
    assert not result.ok
    assert "Denied by user" in result.content
    assert journal.recent(1)[0]["decision"] == "denied_by_user"


async def test_policy_denial_journaled(registry, journal):
    registry.register(WRITE_TOOL)
    result = await registry.execute("test.write", {"path": "/etc/passwd"})
    assert not result.ok
    assert journal.recent(1)[0]["decision"] == "denied_by_policy"


async def test_tool_exception_contained(registry, journal):
    class NoArgs(BaseModel):
        pass

    async def boom(args) -> ToolResult:
        raise RuntimeError("kaboom")

    registry.register(ToolDef(
        name="test.boom", description="boom", args_model=NoArgs,
        risk=RiskLevel.READ, handler=boom,
    ))
    result = await registry.execute("test.boom", {})
    assert not result.ok and "kaboom" in result.content
    entry = journal.recent(1)[0]
    assert entry["result_ok"] == 0 and "kaboom" in entry["error"]


async def test_tool_timeout(policy, journal):
    from kowalski.policy import AutoConfirm
    from kowalski.tools.registry import ToolRegistry

    class NoArgs(BaseModel):
        pass

    async def slow(args) -> ToolResult:
        await asyncio.sleep(5)
        return ToolResult(ok=True, content="late")

    registry = ToolRegistry(policy=policy, journal=journal, confirmer=AutoConfirm(),
                            tool_timeout=0.05)
    registry.register(ToolDef(
        name="test.slow", description="slow", args_model=NoArgs,
        risk=RiskLevel.READ, handler=slow,
    ))
    result = await registry.execute("test.slow", {})
    assert not result.ok and "timed out" in result.content
    assert journal.recent(1)[0]["error"] == "timeout"


# -- danger_check ----------------------------------------------------------


class CmdArgs(BaseModel):
    command: str


def _danger_tool(ran: list[bool]) -> ToolDef:
    async def handler(args: CmdArgs) -> ToolResult:
        ran.append(True)
        return ToolResult(ok=True, content="executed")

    return ToolDef(
        name="test.danger", description="danger", args_model=CmdArgs,
        risk=RiskLevel.DESTRUCTIVE, handler=handler,
        danger_check=lambda a: "boom!" if "boom" in a["command"] else None,
    )


async def test_danger_check_forces_confirm_and_records_reason(policy, journal):
    from kowalski.tools.registry import ToolRegistry

    seen: list[ConfirmRequest] = []

    class Spy:
        async def confirm(self, request) -> bool:
            seen.append(request)
            return True

    ran: list[bool] = []
    registry = ToolRegistry(policy=policy, journal=journal, confirmer=Spy())
    registry.register(_danger_tool(ran))

    result = await registry.execute("test.danger", {"command": "boom now"})
    assert result.ok and ran == [True]
    # The confirm gate saw the danger flag + reason.
    assert len(seen) == 1
    assert seen[0].dangerous is True
    assert seen[0].danger_reason == "boom!"
    assert seen[0].reason == "boom!"


async def test_danger_check_denied_by_autoconfirm_not_executed(policy, journal):
    from kowalski.policy import AutoConfirm
    from kowalski.tools.registry import ToolRegistry

    ran: list[bool] = []
    registry = ToolRegistry(policy=policy, journal=journal, confirmer=AutoConfirm())
    registry.register(_danger_tool(ran))

    result = await registry.execute("test.danger", {"command": "boom now"})
    assert not result.ok
    assert "Denied by user" in result.content
    assert ran == []  # handler never ran
    entry = journal.recent(1)[0]
    assert entry["decision"] == "denied_by_user"
    assert entry["error"] == "boom!"  # danger reason journaled


# -- dry_run ----------------------------------------------------------------


async def test_dry_run_skips_write_execution(policy, journal):
    from kowalski.policy import AutoConfirm
    from kowalski.tools.registry import ToolRegistry

    ran: list[bool] = []

    async def w(args: WriteArgs) -> ToolResult:
        ran.append(True)
        return ToolResult(ok=True, content="written")

    registry = ToolRegistry(
        policy=policy, journal=journal, confirmer=AutoConfirm(), dry_run=True
    )
    registry.register(ToolDef(
        name="test.write", description="write", args_model=WriteArgs,
        risk=RiskLevel.WRITE, handler=w, path_fields=("path",),
    ))

    result = await registry.execute("test.write", {"path": "/tmp/out.txt"})
    assert result.ok
    assert ran == []  # handler must NOT run
    assert result.content.startswith("[dry-run] would call test.write(")
    assert result.data == {
        "dry_run": True, "tool": "test.write", "args": {"path": "/tmp/out.txt"}
    }
    assert journal.recent(1)[0]["decision"] == "dry_run"


async def test_dry_run_read_still_executes(policy, journal):
    from kowalski.policy import AutoConfirm
    from kowalski.tools.registry import ToolRegistry

    registry = ToolRegistry(
        policy=policy, journal=journal, confirmer=AutoConfirm(), dry_run=True
    )
    registry.register(ECHO)

    result = await registry.execute("test.echo", {"text": "hi"})
    assert result.ok and result.content == "echo: hi"
    assert journal.recent(1)[0]["decision"] == "executed"
