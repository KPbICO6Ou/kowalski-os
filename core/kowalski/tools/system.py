"""system.* tools: host diagnostics. Host info (system.cpu_info, system.memory_info,
...) comes from the pydantic-ai-toolbox SystemToolset mounted in bootstrap."""

from __future__ import annotations

import asyncio
import json
import shutil

from pydantic import BaseModel, Field

from .base import RiskLevel, ToolDef, ToolResult


class DiagnosticsArgs(BaseModel):
    check: str | None = Field(
        default=None, description="Specific check to run (e.g. ollama, stt, tts); all if omitted"
    )


async def system_diagnostics(args: DiagnosticsArgs) -> ToolResult:
    """Wraps `wtf audit --format json` (wtftools) when installed."""
    wtf = shutil.which("wtf")
    if not wtf:
        payload = {"available": False, "hint": "install wtftools for diagnostics"}
        return ToolResult(ok=True, content=json.dumps(payload), data=payload)

    cmd = [wtf, "audit", "--format", "json"]
    if args.check:
        cmd += ["--check", args.check]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    try:
        payload = json.loads(stdout.decode())
    except json.JSONDecodeError:
        return ToolResult(ok=False, content=f"wtf returned invalid JSON: {stderr.decode()[:200]}")
    return ToolResult(ok=True, content=json.dumps(payload, ensure_ascii=False), data=payload)


TOOLS = [
    ToolDef(
        name="system.diagnostics",
        description="Run host diagnostics (wtftools audit): service health, latency, GPU, disks.",
        args_model=DiagnosticsArgs,
        risk=RiskLevel.READ,
        handler=system_diagnostics,
    ),
]
