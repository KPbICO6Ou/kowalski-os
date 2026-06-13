"""uiauto.* tools: list/activate windows, read the accessibility tree, and
drive keyboard/mouse through the Desktop seam.

The real adapter (XdotoolDesktop) is Linux/X11 only; tests inject a
MockDesktop. Adapter failures are wrapped into ToolResult(ok=False, ...) so a
missing binary or a flaky window manager never kills the agent loop."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..config import Config
from ..uiauto import Desktop, XdotoolDesktop
from .base import RiskLevel, ToolDef, ToolResult

# Hard cap on accessibility-tree depth so we never feed a giant UI hierarchy
# back to the LLM. Configurable via UIAUTO_TREE_MAX_DEPTH (optional).
DEFAULT_TREE_MAX_DEPTH = 6


class NoArgs(BaseModel):
    pass


class TreeArgs(BaseModel):
    window_id: str | None = Field(
        default=None, description="Window id to inspect; default is the active window"
    )


class ActivateArgs(BaseModel):
    window_id: str = Field(description="Window id to focus/raise")


class TypeArgs(BaseModel):
    text: str = Field(description="Literal text to type into the focused window")


class KeyArgs(BaseModel):
    keys: str = Field(description="Key chord, xdotool spec, e.g. 'ctrl+s' or 'Return'")


class ClickArgs(BaseModel):
    x: int = Field(description="Screen x coordinate")
    y: int = Field(description="Screen y coordinate")
    button: int = Field(default=1, ge=1, description="Mouse button (1=left, 2=middle, 3=right)")


def _trim_tree(node: dict, max_depth: int) -> dict:
    """Return a copy of the tree capped at max_depth. Children beyond the cap
    are dropped and replaced with a marker so the LLM knows it was truncated."""
    role = node.get("role", "")
    name = node.get("name", "")
    children = node.get("children") or []
    if max_depth <= 0:
        out: dict = {"role": role, "name": name}
        if children:
            out["children"] = []
            out["truncated"] = True
        return out
    return {
        "role": role,
        "name": name,
        "children": [_trim_tree(c, max_depth - 1) for c in children],
    }


def build_uiauto_tools(config: Config, desktop: Desktop | None = None) -> list[ToolDef]:
    """Factory for the uiauto.* tools. `desktop` is injectable for tests;
    defaults to the real XdotoolDesktop (Linux/X11). No required config keys;
    UIAUTO_TREE_MAX_DEPTH is an optional override."""
    desk = desktop if desktop is not None else XdotoolDesktop()

    try:
        max_depth = int(config.get("UIAUTO_TREE_MAX_DEPTH", str(DEFAULT_TREE_MAX_DEPTH)))
    except ValueError:
        max_depth = DEFAULT_TREE_MAX_DEPTH

    async def windows_list(args: NoArgs) -> ToolResult:
        try:
            windows = await desk.list_windows()
        except Exception as exc:
            return ToolResult(ok=False, content=f"Could not list windows: {exc}")
        if not windows:
            return ToolResult(ok=True, content="No open windows.", data=[])
        lines = []
        for w in windows:
            mark = "* " if w.get("active") else "  "
            lines.append(f"{mark}{w.get('id')}  [{w.get('app')}]  {w.get('title')}")
        return ToolResult(ok=True, content="\n".join(lines), data=windows)

    async def ui_tree(args: TreeArgs) -> ToolResult:
        try:
            tree = await desk.accessibility_tree(args.window_id)
        except Exception as exc:
            return ToolResult(ok=False, content=f"Could not read accessibility tree: {exc}")
        trimmed = _trim_tree(tree, max_depth)
        target = args.window_id or "active window"
        return ToolResult(ok=True, content=f"Accessibility tree for {target}.", data=trimmed)

    async def windows_activate(args: ActivateArgs) -> ToolResult:
        try:
            ok = await desk.activate_window(args.window_id)
        except Exception as exc:
            return ToolResult(ok=False, content=f"Could not activate window: {exc}")
        if ok:
            return ToolResult(ok=True, content=f"Activated window {args.window_id}.")
        return ToolResult(ok=False, content=f"Window not found: {args.window_id}")

    async def input_type(args: TypeArgs) -> ToolResult:
        try:
            await desk.type_text(args.text)
        except Exception as exc:
            return ToolResult(ok=False, content=f"Could not type text: {exc}")
        return ToolResult(ok=True, content=f"Typed {len(args.text)} character(s).")

    async def input_key(args: KeyArgs) -> ToolResult:
        try:
            await desk.press_keys(args.keys)
        except Exception as exc:
            return ToolResult(ok=False, content=f"Could not press keys: {exc}")
        return ToolResult(ok=True, content=f"Pressed {args.keys}.")

    async def input_click(args: ClickArgs) -> ToolResult:
        try:
            await desk.click(args.x, args.y, args.button)
        except Exception as exc:
            return ToolResult(ok=False, content=f"Could not click: {exc}")
        return ToolResult(ok=True, content=f"Clicked button {args.button} at ({args.x}, {args.y}).")

    return [
        ToolDef(
            name="windows.list",
            description="List open windows with their id, title, app, and active flag.",
            args_model=NoArgs,
            risk=RiskLevel.READ,
            handler=windows_list,
        ),
        ToolDef(
            name="ui.tree",
            description="Read the accessibility tree (role/name/children) of a window.",
            args_model=TreeArgs,
            risk=RiskLevel.READ,
            handler=ui_tree,
        ),
        ToolDef(
            name="windows.activate",
            description="Focus/raise a window by its id.",
            args_model=ActivateArgs,
            risk=RiskLevel.WRITE,
            handler=windows_activate,
        ),
        # DESTRUCTIVE: typed text lands in whatever window is currently focused.
        # If that is a terminal it can run arbitrary commands, so this must always
        # require confirmation regardless of args.
        ToolDef(
            name="input.type",
            description="Type literal text into the currently focused window.",
            args_model=TypeArgs,
            risk=RiskLevel.DESTRUCTIVE,
            handler=input_type,
        ),
        # DESTRUCTIVE: key chords (e.g. ctrl+w, Return) act on the focused window
        # and can trigger destructive shortcuts; always confirm.
        ToolDef(
            name="input.key",
            description="Press a key chord (xdotool spec, e.g. 'ctrl+s', 'Return').",
            args_model=KeyArgs,
            risk=RiskLevel.DESTRUCTIVE,
            handler=input_key,
        ),
        # DESTRUCTIVE: a click at arbitrary coordinates can hit any UI control;
        # always confirm.
        ToolDef(
            name="input.click",
            description="Move the pointer to (x, y) and click the given mouse button.",
            args_model=ClickArgs,
            risk=RiskLevel.DESTRUCTIVE,
            handler=input_click,
        ),
    ]
