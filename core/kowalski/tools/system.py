"""system.* tools: host info and diagnostics.

NOTE: планируется замена на SystemToolset из pydantic-ai-toolbox, когда тот
появится в upstream (см. roadmap, раздел pydantic-ai-toolbox)."""

from __future__ import annotations

import asyncio
import json
import shutil
from typing import Literal

from pydantic import BaseModel, Field

from .base import RiskLevel, ToolDef, ToolResult

Section = Literal["cpu", "memory", "disk", "battery", "uptime", "load"]


class SystemInfoArgs(BaseModel):
    sections: list[Section] = Field(
        default=["cpu", "memory", "disk"],
        description="Which sections of system information to return",
    )


async def system_info(args: SystemInfoArgs) -> ToolResult:
    import psutil

    info: dict = {}
    if "cpu" in args.sections:
        info["cpu"] = {
            "cores": psutil.cpu_count(logical=False),
            "threads": psutil.cpu_count(),
            "percent": psutil.cpu_percent(interval=0.1),
        }
    if "memory" in args.sections:
        mem = psutil.virtual_memory()
        info["memory"] = {
            "total_gb": round(mem.total / 2**30, 1),
            "available_gb": round(mem.available / 2**30, 1),
            "percent": mem.percent,
        }
    if "disk" in args.sections:
        disk = psutil.disk_usage("/")
        # psutil's `percent` is misleading on macOS (APFS snapshot volume) —
        # report an unambiguous used_percent computed from total/free instead
        info["disk"] = {
            "total_gb": round(disk.total / 2**30, 1),
            "free_gb": round(disk.free / 2**30, 1),
            "used_percent": round((disk.total - disk.free) / disk.total * 100, 1),
        }
    if "battery" in args.sections:
        battery = psutil.sensors_battery()
        info["battery"] = (
            {"percent": battery.percent, "plugged": battery.power_plugged} if battery else None
        )
    if "uptime" in args.sections:
        import time

        info["uptime_hours"] = round((time.time() - psutil.boot_time()) / 3600, 1)
    if "load" in args.sections:
        info["load_avg"] = psutil.getloadavg()
    return ToolResult(ok=True, content=json.dumps(info, ensure_ascii=False), data=info)


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
        name="system.info",
        description="Get host system information: CPU, memory, disk, battery, uptime, load.",
        args_model=SystemInfoArgs,
        risk=RiskLevel.READ,
        handler=system_info,
    ),
    ToolDef(
        name="system.diagnostics",
        description="Run host diagnostics (wtftools audit): service health, latency, GPU, disks.",
        args_model=DiagnosticsArgs,
        risk=RiskLevel.READ,
        handler=system_diagnostics,
    ),
]
