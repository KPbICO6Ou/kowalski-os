from pathlib import Path

from kowalski.plugins import DEFAULT_PLUGINS_DIR, load_plugin_tools
from kowalski.tools.base import RiskLevel, ToolDef, ToolResult

GOOD_PLUGIN = '''
from pydantic import BaseModel

from kowalski.tools.base import RiskLevel, ToolDef, ToolResult


class EchoArgs(BaseModel):
    text: str = "hi"


async def echo(args: EchoArgs) -> ToolResult:
    return ToolResult(ok=True, content=f"echo: {args.text}")


TOOLS = [
    ToolDef(
        name="example.echo",
        description="Echo text back.",
        args_model=EchoArgs,
        risk=RiskLevel.READ,
        handler=echo,
    )
]
'''


async def test_load_good_plugin_returns_callable_tool(tmp_path: Path):
    (tmp_path / "echo.py").write_text(GOOD_PLUGIN)
    tools = load_plugin_tools(tmp_path)
    assert len(tools) == 1
    tool = tools[0]
    assert isinstance(tool, ToolDef)
    assert tool.name == "example.echo"
    assert tool.risk == RiskLevel.READ
    result = await tool.handler(tool.args_model(text="yo"))
    assert isinstance(result, ToolResult)
    assert result.ok
    assert result.content == "echo: yo"


def test_underscore_files_skipped(tmp_path: Path):
    (tmp_path / "echo.py").write_text(GOOD_PLUGIN)
    (tmp_path / "_private.py").write_text(GOOD_PLUGIN.replace("example.echo", "example.private"))
    names = {t.name for t in load_plugin_tools(tmp_path)}
    assert names == {"example.echo"}


def test_syntax_error_plugin_skipped(tmp_path: Path):
    (tmp_path / "good.py").write_text(GOOD_PLUGIN)
    (tmp_path / "broken.py").write_text("this is not valid python :::")
    tools = load_plugin_tools(tmp_path)
    assert [t.name for t in tools] == ["example.echo"]


def test_wrong_tools_type_skipped(tmp_path: Path):
    (tmp_path / "good.py").write_text(GOOD_PLUGIN)
    # ARIA-style dict shape, not our list[ToolDef]
    (tmp_path / "ariastyle.py").write_text("TOOLS = {'name': 'aria.tool'}\n")
    (tmp_path / "notools.py").write_text("X = 1\n")
    tools = load_plugin_tools(tmp_path)
    assert [t.name for t in tools] == ["example.echo"]


def test_non_tooldef_entries_skipped(tmp_path: Path):
    (tmp_path / "mixed.py").write_text(
        GOOD_PLUGIN + "\nTOOLS = TOOLS + ['not a tooldef', 42]\n"
    )
    tools = load_plugin_tools(tmp_path)
    assert [t.name for t in tools] == ["example.echo"]


def test_missing_dir_returns_empty(tmp_path: Path):
    missing = tmp_path / "nope" / "deeper"
    assert load_plugin_tools(missing) == []


def test_default_plugins_dir_is_expanded():
    assert DEFAULT_PLUGINS_DIR.is_absolute()
    assert "~" not in str(DEFAULT_PLUGINS_DIR)
