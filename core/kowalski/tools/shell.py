"""shell.* tools: sandboxed arbitrary command execution.

system.run is the highest-risk capability the agent has: arbitrary shell can
read, modify, or destroy anything the user can. It is therefore marked
DESTRUCTIVE — the registry/policy ALWAYS confirms a DESTRUCTIVE tool and never
auto-allows it. Execution itself goes through a SandboxRunner: a real
bubblewrap/firejail sandbox on Linux, an unsandboxed (loudly warned) fallback
on macOS/CI.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ..config import Config
from ..sandbox import RunResult, SandboxRunner, default_runner
from .base import RiskLevel, ToolDef, ToolResult

# Hard ceiling on the per-command timeout, independent of config.
MAX_TIMEOUT = 300.0


class ShellRunArgs(BaseModel):
    command: str = Field(min_length=1, description="Shell command to execute")
    cwd: str | None = Field(
        default=None,
        description="Working directory (must be inside an allowed path); default: first allowed path",
    )
    timeout: float = Field(
        default=30.0, gt=0, le=MAX_TIMEOUT, description="Seconds before the command is killed"
    )


def _format_result(result: RunResult) -> str:
    marker = "" if result.sandboxed else " (unsandboxed)"
    lines = [f"exit code: {result.exit_code}{marker}"]
    if result.timed_out:
        lines.append("status: TIMED OUT")
    if result.stdout:
        lines.append(f"stdout:\n{result.stdout}")
    if result.stderr:
        lines.append(f"stderr:\n{result.stderr}")
    return "\n".join(lines)


def build_shell_tools(config: Config, runner: SandboxRunner | None = None) -> list[ToolDef]:
    """Factory for shell.* tools.

    Optional config keys:
      * KOW_SHELL_TIMEOUT: default per-command timeout in seconds (default 30,
        capped at MAX_TIMEOUT=300).
    Uses config.allowed_paths to validate cwd.
    """
    runner = runner or default_runner()
    allowed_paths = config.allowed_paths
    try:
        default_timeout = min(float(config.get("KOW_SHELL_TIMEOUT", "30")), MAX_TIMEOUT)
    except ValueError:
        default_timeout = 30.0

    async def system_run(args: ShellRunArgs) -> ToolResult:
        # Resolve and validate cwd against the allowlist BEFORE running anything.
        if args.cwd is not None:
            cwd = Path(args.cwd).expanduser().resolve()
        elif allowed_paths:
            cwd = allowed_paths[0]
        else:
            cwd = Path.home().resolve()

        if not any(cwd.is_relative_to(p) for p in allowed_paths):
            return ToolResult(
                ok=False,
                content=f"Refusing to run: cwd {cwd} is outside allowed paths.",
            )
        if not cwd.is_dir():
            return ToolResult(ok=False, content=f"Working directory does not exist: {cwd}")

        timeout = min(args.timeout, MAX_TIMEOUT)
        result = await runner.run(args.command, cwd=str(cwd), timeout=timeout)

        data = {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": result.timed_out,
            "sandboxed": result.sandboxed,
        }
        content = _format_result(result)
        if result.timed_out:
            return ToolResult(
                ok=False, content=f"Command timed out after {timeout}s.\n{content}", data=data
            )
        ok = result.exit_code == 0
        return ToolResult(ok=ok, content=content, data=data)

    return [
        ToolDef(
            # DESTRUCTIVE: arbitrary shell is the highest-risk capability, so it
            # is always confirmed by the registry and never auto-allowed. It is
            # sandboxed when bwrap/firejail are present (Linux), unsandboxed on
            # macOS/CI (PlainRunner warns loudly).
            name="system.run",
            description=(
                "Run an arbitrary shell command (sandboxed on Linux via "
                "bubblewrap/firejail; unsandboxed fallback on macOS/CI). "
                f"Default timeout {int(default_timeout)}s."
            ),
            args_model=ShellRunArgs,
            risk=RiskLevel.DESTRUCTIVE,
            handler=system_run,
            path_fields=("cwd",),
        ),
    ]
