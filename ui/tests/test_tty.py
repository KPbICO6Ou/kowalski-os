"""tty REPL formatting helpers (no GTK, no terminal interaction needed)."""

from __future__ import annotations

from kowui.tty import format_confirm_prompt, format_tool_line


def test_format_tool_line():
    line = format_tool_line("fs.write", {"path": "/tmp/x", "mode": 644})
    assert line == "→ fs.write(path='/tmp/x', mode=644)"


def test_format_tool_line_no_args():
    assert format_tool_line("sys.status", {}) == "→ sys.status()"


def test_format_confirm_prompt():
    line = format_confirm_prompt("fs.write", "write", "writes outside the allowlist")
    assert line == "confirm fs.write [write]: writes outside the allowlist"
