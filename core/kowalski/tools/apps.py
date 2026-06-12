"""apps.* tools: open applications, files, and URLs."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from .. import platform
from .base import RiskLevel, ToolDef, ToolResult


class AppOpenArgs(BaseModel):
    app: str | None = Field(default=None, description="Application name to launch")
    path: str | None = Field(default=None, description="File, directory, or http(s) URL to open")

    @model_validator(mode="after")
    def exactly_one(self) -> "AppOpenArgs":
        if bool(self.app) == bool(self.path):
            raise ValueError("provide exactly one of 'app' or 'path'")
        return self


async def apps_open(args: AppOpenArgs) -> ToolResult:
    if args.app:
        ok, detail = await platform.open_app(args.app)
        what = f"application {args.app}"
    else:
        target = str(args.path)
        if "://" in target and not target.startswith(("http://", "https://")):
            return ToolResult(ok=False, content="Only http/https URLs can be opened.")
        ok, detail = await platform.open_path(target)
        what = target
    if ok:
        return ToolResult(ok=True, content=f"Opened {what}.")
    return ToolResult(ok=False, content=f"Failed to open {what}: {detail}")


TOOLS = [
    ToolDef(
        name="apps.open",
        description="Open an application by name, or a file/directory/URL with the default app.",
        args_model=AppOpenArgs,
        risk=RiskLevel.WRITE,
        handler=apps_open,
        path_fields=("path",),
    )
]
