"""Screen capture backends.

System backends shell out to native screenshot tools (lazily detected via
shutil.which) and return PNG bytes for the primary screen. A mock backend
returns canned bytes for tests so no real screen is touched.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from typing import Protocol, runtime_checkable

# Smallest valid 1x1 transparent PNG; handy as a canned screenshot in tests.
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
    b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@runtime_checkable
class ScreenCapturer(Protocol):
    async def capture(self) -> bytes:
        """Return PNG bytes of the primary screen."""
        ...


class CaptureError(RuntimeError):
    """Raised when a screenshot could not be taken."""


class SystemScreenCapturer:
    """Capture the primary screen via a native, OS-specific screenshot tool.

    macOS uses the built-in `screencapture`. Linux prefers `maim`, then falls
    back to `xfce4-screenshooter` or ImageMagick's `import`. The tool is
    detected lazily so importing this module never requires a display.
    """

    async def capture(self) -> bytes:
        cmd = self._build_command()
        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="kow-screen-")
        os.close(fd)
        try:
            full_cmd = [*cmd, tmp_path]
            proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                detail = stderr.decode(errors="replace").strip()
                raise CaptureError(
                    f"screenshot tool '{cmd[0]}' failed (exit {proc.returncode}): {detail}"
                )
            with open(tmp_path, "rb") as fh:
                data = fh.read()
            if not data:
                raise CaptureError(f"screenshot tool '{cmd[0]}' produced an empty file")
            return data
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    @staticmethod
    def _build_command() -> list[str]:
        """Return the argv prefix for the available tool; the output path is appended."""
        import sys

        if sys.platform == "darwin":
            tool = shutil.which("screencapture")
            if tool:
                # -x: no sound, -t png: PNG output
                return [tool, "-x", "-t", "png"]
            raise CaptureError(
                "no screenshot tool found — 'screencapture' is missing (it ships with macOS)"
            )

        # Linux / other POSIX
        maim = shutil.which("maim")
        if maim:
            return [maim]
        shooter = shutil.which("xfce4-screenshooter")
        if shooter:
            return [shooter, "-f", "-s"]
        imagemagick = shutil.which("import")
        if imagemagick:
            # capture the root window (whole screen)
            return [imagemagick, "-window", "root"]
        raise CaptureError(
            "no screenshot tool found — install one of: maim, xfce4-screenshooter, "
            "or ImageMagick (provides 'import')"
        )


class MockScreenCapturer:
    """Test double: returns canned PNG bytes and counts capture() calls."""

    def __init__(self, png: bytes = _TINY_PNG):
        self.png = png
        self.calls = 0

    async def capture(self) -> bytes:
        self.calls += 1
        return self.png
