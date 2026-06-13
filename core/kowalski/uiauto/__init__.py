"""UI automation seam: a Desktop abstraction over window management,
the accessibility tree, and keyboard/mouse input.

The real adapter (XdotoolDesktop) targets Linux/X11 (wmctrl/xdotool/AT-SPI)
and is honest-but-untested-in-CI; the tools are tested entirely through
MockDesktop so they run on any platform."""

from __future__ import annotations

from .desktop import Desktop, MockDesktop, XdotoolDesktop

__all__ = ["Desktop", "MockDesktop", "XdotoolDesktop"]
