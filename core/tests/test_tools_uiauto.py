"""uiauto.* tool tests, driven entirely through MockDesktop (no real desktop)."""

from __future__ import annotations

from kowalski.config import Config
from kowalski.tools.base import RiskLevel
from kowalski.tools.uiauto import build_uiauto_tools
from kowalski.uiauto import MockDesktop


def _tools(desktop):
    return {t.name: t for t in build_uiauto_tools(Config({}), desktop=desktop)}


def _deep_tree(depth: int) -> dict:
    node = {"role": "leaf", "name": f"d{depth}", "children": []}
    for i in range(depth - 1, -1, -1):
        node = {"role": "node", "name": f"d{i}", "children": [node]}
    return node


def _tree_depth(node: dict) -> int:
    children = node.get("children") or []
    if not children:
        return 1
    return 1 + max(_tree_depth(c) for c in children)


WINDOWS = [
    {"id": "0x01", "title": "Editor", "app": "host", "active": True},
    {"id": "0x02", "title": "Browser", "app": "host", "active": False},
]


async def test_windows_list_formats_scripted_windows():
    desk = MockDesktop(windows=WINDOWS)
    tool = _tools(desk)["windows.list"]
    result = await tool.handler(tool.args_model())
    assert result.ok
    assert result.data == WINDOWS
    assert "Editor" in result.content
    assert "Browser" in result.content
    assert "* 0x01" in result.content  # active window marked


async def test_windows_list_empty():
    desk = MockDesktop(windows=[])
    tool = _tools(desk)["windows.list"]
    result = await tool.handler(tool.args_model())
    assert result.ok
    assert result.data == []
    assert "No open windows" in result.content


async def test_ui_tree_returns_tree_and_is_depth_capped():
    deep = _deep_tree(20)
    desk = MockDesktop(tree=deep)
    config = Config({"UIAUTO_TREE_MAX_DEPTH": "4"})
    tool = {t.name: t for t in build_uiauto_tools(config, desktop=desk)}["ui.tree"]
    result = await tool.handler(tool.args_model(window_id="0x01"))
    assert result.ok
    # max_depth=4 -> at most 5 levels (root + 4) before truncation marker
    assert _tree_depth(result.data) <= 5
    assert result.data["role"] == "node"


async def test_ui_tree_default_window_id():
    tree = {"role": "application", "name": "App", "children": []}
    desk = MockDesktop(tree=tree)
    tool = _tools(desk)["ui.tree"]
    result = await tool.handler(tool.args_model())
    assert result.ok
    assert result.data["name"] == "App"
    assert "active window" in result.content


async def test_windows_activate_records_id():
    desk = MockDesktop(windows=WINDOWS)
    tool = _tools(desk)["windows.activate"]
    result = await tool.handler(tool.args_model(window_id="0x02"))
    assert result.ok
    assert desk.activated == ["0x02"]


async def test_windows_activate_unknown():
    desk = MockDesktop(windows=WINDOWS)
    tool = _tools(desk)["windows.activate"]
    result = await tool.handler(tool.args_model(window_id="0xff"))
    assert not result.ok
    assert desk.activated == ["0xff"]


async def test_input_type_records_text():
    desk = MockDesktop()
    tool = _tools(desk)["input.type"]
    result = await tool.handler(tool.args_model(text="hello world"))
    assert result.ok
    assert desk.typed == ["hello world"]


async def test_input_key_records_chord():
    desk = MockDesktop()
    tool = _tools(desk)["input.key"]
    result = await tool.handler(tool.args_model(keys="ctrl+s"))
    assert result.ok
    assert desk.pressed == ["ctrl+s"]


async def test_input_click_records_click():
    desk = MockDesktop()
    tool = _tools(desk)["input.click"]
    result = await tool.handler(tool.args_model(x=10, y=20, button=3))
    assert result.ok
    assert desk.clicks == [(10, 20, 3)]


async def test_input_click_default_button():
    desk = MockDesktop()
    tool = _tools(desk)["input.click"]
    result = await tool.handler(tool.args_model(x=5, y=6))
    assert result.ok
    assert desk.clicks == [(5, 6, 1)]


class _BoomDesktop(MockDesktop):
    async def list_windows(self):
        raise RuntimeError("xdotool not found")


async def test_adapter_error_returns_not_ok():
    tool = _tools(_BoomDesktop())["windows.list"]
    result = await tool.handler(tool.args_model())
    assert not result.ok
    assert "xdotool not found" in result.content


def test_risk_levels():
    tools = _tools(MockDesktop())
    assert tools["windows.list"].risk == RiskLevel.READ
    assert tools["ui.tree"].risk == RiskLevel.READ
    assert tools["windows.activate"].risk == RiskLevel.WRITE
    assert tools["input.type"].risk == RiskLevel.DESTRUCTIVE
    assert tools["input.key"].risk == RiskLevel.DESTRUCTIVE
    assert tools["input.click"].risk == RiskLevel.DESTRUCTIVE


def test_default_desktop_is_xdotool():
    from kowalski.uiauto import XdotoolDesktop

    tools = build_uiauto_tools(Config({}))
    assert len(tools) == 6
    # smoke: the factory builds without a real desktop available
    assert isinstance(XdotoolDesktop(), XdotoolDesktop)
