"""screen.* tools: capture a screenshot and describe what is on screen.

These are RiskLevel.READ tools: screen content is sensitive, but capturing it
to a file or sending it to a vision model does not mutate the system. The
production vision model is qwen2.5-vl / llava served via Ollama; capture uses a
native, OS-specific screenshot tool (screencapture / maim / etc.).
"""

from __future__ import annotations

import os
import time

from pydantic import BaseModel, Field

from ..vision.capture import ScreenCapturer, SystemScreenCapturer
from ..vision.describe import OllamaVisionModel, VisionModel
from .base import RiskLevel, ToolDef, ToolResult


class CaptureArgs(BaseModel):
    path: str | None = Field(
        default=None,
        description="Where to save the PNG; defaults to a temp file under the user cache dir.",
    )


class DescribeArgs(BaseModel):
    prompt: str = Field(
        default="What is on the screen right now? Be concise.",
        description="Question to ask the vision model about the screenshot.",
    )


def _cache_dir() -> str:
    """User cache dir for screenshots (XDG_CACHE_HOME or ~/.cache), kowalski subdir."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    target = os.path.join(base, "kowalski", "screenshots")
    os.makedirs(target, exist_ok=True)
    return target


def _default_path() -> str:
    return os.path.join(_cache_dir(), f"screen-{int(time.time() * 1000)}.png")


def build_vision_tools(
    config,
    capturer: ScreenCapturer | None = None,
    model: VisionModel | None = None,
) -> list[ToolDef]:
    """Build the screen.* READ tools.

    The default capturer and vision model are constructed lazily inside the
    handlers (so importing this module never requires a display or Ollama), but
    both can be injected via the factory params for tests.
    """

    def _capturer() -> ScreenCapturer:
        return capturer if capturer is not None else SystemScreenCapturer()

    def _model() -> VisionModel:
        if model is not None:
            return model
        return OllamaVisionModel(
            host=config.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
            model=config.get("KOW_VISION_MODEL", "qwen2.5vl"),
        )

    async def screen_capture(args: CaptureArgs) -> ToolResult:
        try:
            png = await _capturer().capture()
        except Exception as exc:
            return ToolResult(
                ok=False,
                content=f"Screen capture failed: {exc}",
            )
        path = args.path or _default_path()
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(png)
        except OSError as exc:
            return ToolResult(ok=False, content=f"Could not write screenshot to {path}: {exc}")
        size = len(png)
        return ToolResult(
            ok=True,
            content=f"Saved screenshot to {path} ({size} bytes).",
            data={"path": path, "bytes": size},
        )

    async def screen_describe(args: DescribeArgs) -> ToolResult:
        try:
            png = await _capturer().capture()
        except Exception as exc:
            return ToolResult(ok=False, content=f"Screen capture failed: {exc}")
        try:
            description = await _model().describe(png, args.prompt)
        except Exception as exc:
            return ToolResult(
                ok=False,
                content=f"Vision model failed: {exc}",
            )
        return ToolResult(
            ok=True,
            content=description,
            data={"description": description},
        )

    return [
        ToolDef(
            name="screen.capture",
            description=(
                "Capture a screenshot of the primary screen and save it as a PNG. "
                "Returns the file path and size."
            ),
            args_model=CaptureArgs,
            risk=RiskLevel.READ,
            handler=screen_capture,
            path_fields=("path",),
        ),
        ToolDef(
            name="screen.describe",
            description=(
                "Capture the primary screen and ask a vision model what is on it. "
                "Returns a text description."
            ),
            args_model=DescribeArgs,
            risk=RiskLevel.READ,
            handler=screen_describe,
        ),
    ]
