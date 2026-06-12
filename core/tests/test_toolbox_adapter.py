"""Tests for mounting pydantic-ai-toolbox toolsets into the registry."""

from pathlib import Path

import pytest

pytest.importorskip("pydantic_ai_toolbox")

from kowalski.tools.base import RiskLevel  # noqa: E402
from kowalski.tools.toolbox import (  # noqa: E402
    build_filesystem_tools,
    build_system_tools,
    classify_risk,
)


def test_risk_classification():
    assert classify_risk("read_file") == RiskLevel.READ
    assert classify_risk("list_dir") == RiskLevel.READ
    assert classify_risk("grep") == RiskLevel.READ
    assert classify_risk("write_file") == RiskLevel.WRITE
    assert classify_risk("move") == RiskLevel.WRITE
    assert classify_risk("delete_file") == RiskLevel.DESTRUCTIVE
    assert classify_risk("delete_dir") == RiskLevel.DESTRUCTIVE


def test_fs_tools_mounted(tmp_path: Path):
    tools = build_filesystem_tools(root=tmp_path, read_only=True)
    names = {t.name for t in tools}
    assert "fs.read_file" in names
    assert "fs.list_dir" in names
    assert "fs.grep" in names
    # all namespaced, schemas generated from signatures
    read_file = next(t for t in tools if t.name == "fs.read_file")
    assert "path" in read_file.input_schema["properties"]


async def test_fs_read_through_registry(tmp_path: Path, registry):
    (tmp_path / "hello.txt").write_text("привет мир")
    registry.register_all(build_filesystem_tools(root=tmp_path, read_only=True))
    result = await registry.execute("fs.read_file", {"path": "hello.txt"})
    assert result.ok
    assert "привет мир" in result.content


async def test_fs_sandbox_escape_contained(tmp_path: Path, registry):
    registry.register_all(build_filesystem_tools(root=tmp_path, read_only=True))
    result = await registry.execute("fs.read_file", {"path": "../../etc/passwd"})
    assert not result.ok
    assert "escapes sandbox" in result.content


async def test_fs_write_blocked_when_read_only(tmp_path: Path, registry):
    registry.register_all(build_filesystem_tools(root=tmp_path, read_only=True))
    # write_file is WRITE risk; path inside tmp allowlist -> policy allows,
    # but the toolset itself is read-only and must refuse
    result = await registry.execute("fs.write_file", {"path": "x.txt", "content": "no"})
    assert not result.ok
    assert "read-only" in result.content


def test_system_tools_mounted():
    tools = build_system_tools()
    names = {t.name for t in tools}
    assert {
        "system.cpu_info",
        "system.memory_info",
        "system.disk_usage",
        "system.disk_partitions",
        "system.uptime",
        "system.load_avg",
        "system.top_processes",
        "system.network_io",
        "system.battery",
    } <= names
    # method names (cpu_info, battery, ...) don't match READ prefixes —
    # the risk_override must force every tool to READ
    assert all(t.risk == RiskLevel.READ for t in tools)


async def test_system_disk_usage_through_registry(registry):
    registry.register_all(build_system_tools())
    result = await registry.execute("system.disk_usage", {})
    assert result.ok
    assert isinstance(result.data, dict)
    assert result.data  # non-empty payload with disk numbers
    assert any("total" in key for key in result.data)


async def test_fs_delete_requires_confirmation(tmp_path: Path, deny_registry):
    (tmp_path / "victim.txt").write_text("x")
    deny_registry.register_all(build_filesystem_tools(root=tmp_path, read_only=False))
    result = await deny_registry.execute("fs.delete_file", {"path": "victim.txt"})
    assert not result.ok
    assert "Denied by user" in result.content
    assert (tmp_path / "victim.txt").exists()  # nothing was deleted
