"""shell.* tool tests. These run on macOS/CI with the unsandboxed PlainRunner
(default_runner falls back to it when bwrap/firejail are absent), so behaviour
under test is the timeout/cwd/truncation logic, not the Linux isolation."""

import time
from pathlib import Path

from kowalski.config import Config
from kowalski.sandbox import MAX_OUTPUT_BYTES, PlainRunner
from kowalski.tools.base import RiskLevel
from kowalski.tools.shell import ShellRunArgs, build_shell_tools


def _config(allowed: Path) -> Config:
    return Config(values={"KOW_ALLOWED_PATHS": str(allowed)})


def _tool(allowed: Path):
    # Pin PlainRunner so the suite is deterministic regardless of host.
    return build_shell_tools(_config(allowed), runner=PlainRunner())[0]


async def test_echo_hello(tmp_path: Path):
    tool = _tool(tmp_path)
    result = await tool.handler(ShellRunArgs(command="echo hello", cwd=str(tmp_path)))
    assert result.ok
    assert "hello" in result.content
    assert result.data["exit_code"] == 0


async def test_nonzero_exit(tmp_path: Path):
    tool = _tool(tmp_path)
    result = await tool.handler(ShellRunArgs(command="sh -c 'exit 3'", cwd=str(tmp_path)))
    assert not result.ok
    assert result.data["exit_code"] == 3


async def test_timeout(tmp_path: Path):
    tool = _tool(tmp_path)
    started = time.perf_counter()
    result = await tool.handler(
        ShellRunArgs(command="sleep 5", cwd=str(tmp_path), timeout=0.2)
    )
    elapsed = time.perf_counter() - started
    assert result.data["timed_out"] is True
    assert not result.ok
    assert elapsed < 4.0  # returned promptly, did not wait out the sleep


async def test_cwd_outside_allowlist_rejected(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    tool = _tool(allowed)
    # A command that would leave a side-effect if it ran.
    marker = outside / "ran.txt"
    result = await tool.handler(
        ShellRunArgs(command=f"touch {marker}", cwd=str(outside))
    )
    assert not result.ok
    assert "outside allowed paths" in result.content
    assert not marker.exists()  # command must NOT have run


async def test_output_truncation(tmp_path: Path):
    tool = _tool(tmp_path)
    # Emit more than the cap so truncation kicks in.
    nbytes = MAX_OUTPUT_BYTES + 5000
    result = await tool.handler(
        ShellRunArgs(command=f"head -c {nbytes} /dev/zero | tr '\\0' 'a'", cwd=str(tmp_path))
    )
    assert result.ok
    assert "output truncated" in result.data["stdout"]
    assert len(result.data["stdout"]) < nbytes


def test_risk_is_destructive(tmp_path: Path):
    tool = _tool(tmp_path)
    assert tool.risk == RiskLevel.DESTRUCTIVE


def test_danger_check_wired(tmp_path: Path):
    tool = _tool(tmp_path)
    assert tool.danger_check is not None
    assert tool.danger_check({"command": "rm -rf /"}) is not None
    assert tool.danger_check({"command": "ls -la"}) is None
    assert tool.danger_check({}) is None  # missing command -> no crash


async def test_secret_env_not_leaked_to_command(tmp_path, monkeypatch):
    """A secret in the agent's environment must not reach the executed command
    (the sandbox isolates fs/network; env must be scrubbed too)."""
    from kowalski.config import Config
    from kowalski.tools.shell import build_shell_tools, ShellRunArgs

    monkeypatch.setenv("IMAP_PASSWORD", "super-secret-token")
    config = Config({"KOW_ALLOWED_PATHS": str(tmp_path)})
    tool = build_shell_tools(config)[0]
    result = await tool.handler(ShellRunArgs(command="echo PW=[$IMAP_PASSWORD]", cwd=str(tmp_path)))
    assert result.ok
    assert "super-secret-token" not in result.data["stdout"]
    assert "PW=[]" in result.data["stdout"]


async def test_configured_default_timeout_applies(tmp_path):
    from kowalski.config import Config
    from kowalski.tools.shell import build_shell_tools, ShellRunArgs

    config = Config({"KOW_ALLOWED_PATHS": str(tmp_path), "KOW_SHELL_TIMEOUT": "0.2"})
    tool = build_shell_tools(config)[0]
    # no explicit timeout -> uses the configured 0.2s default -> times out
    result = await tool.handler(ShellRunArgs(command="sleep 5", cwd=str(tmp_path)))
    assert not result.ok
    assert result.data["timed_out"] is True
