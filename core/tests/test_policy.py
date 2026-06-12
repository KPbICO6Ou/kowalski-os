from pathlib import Path

import pytest
from pydantic import BaseModel

from kowalski.policy import Decision, SecurityPolicy
from kowalski.tools.base import RiskLevel, ToolDef, ToolResult


class PathArgs(BaseModel):
    path: str | None = None


def make_tool(risk: RiskLevel, path_fields=("path",)) -> ToolDef:
    async def handler(args) -> ToolResult:
        return ToolResult(ok=True, content="done")

    return ToolDef(
        name=f"test.{risk}",
        description="test tool",
        args_model=PathArgs,
        risk=risk,
        handler=handler,
        path_fields=path_fields,
    )


@pytest.fixture
def policy(tmp_path: Path) -> SecurityPolicy:
    return SecurityPolicy(allowed_paths=[tmp_path])


def test_read_always_allowed(policy: SecurityPolicy):
    decision, _ = policy.evaluate(make_tool(RiskLevel.READ), {})
    assert decision == Decision.ALLOW


def test_write_inside_allowlist_allowed(policy: SecurityPolicy, tmp_path: Path):
    decision, _ = policy.evaluate(make_tool(RiskLevel.WRITE), {"path": str(tmp_path / "f.txt")})
    assert decision == Decision.ALLOW


def test_write_outside_allowlist_confirms(policy: SecurityPolicy):
    decision, _ = policy.evaluate(make_tool(RiskLevel.WRITE), {"path": "/tmp/elsewhere.txt"})
    assert decision == Decision.CONFIRM


def test_destructive_always_confirms(policy: SecurityPolicy, tmp_path: Path):
    decision, _ = policy.evaluate(
        make_tool(RiskLevel.DESTRUCTIVE), {"path": str(tmp_path / "f")}
    )
    assert decision == Decision.CONFIRM


def test_network_confirms_by_default(policy: SecurityPolicy):
    decision, _ = policy.evaluate(make_tool(RiskLevel.NETWORK), {})
    assert decision == Decision.CONFIRM


def test_network_auto_allow(tmp_path: Path):
    policy = SecurityPolicy(allowed_paths=[tmp_path], auto_allow_network=True)
    decision, _ = policy.evaluate(make_tool(RiskLevel.NETWORK), {})
    assert decision == Decision.ALLOW


def test_forbidden_root_denied(policy: SecurityPolicy):
    decision, reason = policy.evaluate(make_tool(RiskLevel.WRITE), {"path": "/etc/passwd"})
    assert decision == Decision.DENY
    assert "outside permitted" in reason


def test_symlink_escape_denied(policy: SecurityPolicy, tmp_path: Path):
    evil = tmp_path / "link"
    evil.symlink_to("/etc")
    decision, _ = policy.evaluate(make_tool(RiskLevel.WRITE), {"path": str(evil / "passwd")})
    assert decision == Decision.DENY
