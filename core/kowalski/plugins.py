"""Plugin folder loader: discover extra tools dropped into a directory.

Each plugin is a plain ``*.py`` file that exports a module-level ``TOOLS``
list of :class:`~kowalski.tools.base.ToolDef` (our native shape, NOT ARIA's
dict shape). Files are imported in isolation; one broken plugin never takes
down the others or the daemon — load errors and wrong-typed exports are
logged and skipped.

Example plugin file (``~/.config/kowalski/plugins/hello.py``)::

    from pydantic import BaseModel, Field

    from kowalski.tools.base import RiskLevel, ToolDef, ToolResult


    class HelloArgs(BaseModel):
        name: str = Field(default="world", min_length=1)


    async def hello(args: HelloArgs) -> ToolResult:
        return ToolResult(ok=True, content=f"Hello, {args.name}!")


    TOOLS = [
        ToolDef(
            name="example.hello",
            description="Greet someone by name.",
            args_model=HelloArgs,
            risk=RiskLevel.READ,
            handler=hello,
        )
    ]
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from .tools.base import ToolDef

logger = logging.getLogger(__name__)

DEFAULT_PLUGINS_DIR = Path("~/.config/kowalski/plugins").expanduser()


def _load_one(path: Path) -> list[ToolDef]:
    """Import a single plugin file and return its validated ToolDefs.

    Returns an empty list (and logs) on any error or wrong-typed export;
    never raises.
    """
    module_name = f"kowalski_plugin_{path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.warning("plugin %s: could not create import spec; skipping", path)
            return []
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # plugin code is untrusted; isolate failures
        logger.warning("plugin %s failed to import: %r; skipping", path, exc)
        return []

    tools = getattr(module, "TOOLS", None)
    if not isinstance(tools, list):
        logger.warning(
            "plugin %s: TOOLS missing or not a list (got %s); skipping",
            path,
            type(tools).__name__,
        )
        return []

    valid: list[ToolDef] = []
    for item in tools:
        if isinstance(item, ToolDef):
            valid.append(item)
        else:
            logger.warning(
                "plugin %s: TOOLS entry is not a ToolDef (got %s); skipping entry",
                path,
                type(item).__name__,
            )
    return valid


def load_plugin_tools(directory: Path) -> list[ToolDef]:
    """Scan ``directory/*.py`` and return all ToolDefs exported via ``TOOLS``.

    Files whose name starts with ``_`` are ignored. A missing directory is
    created (best effort) and yields an empty list. Individual plugin errors
    are logged and skipped — this function never raises.
    """
    if not directory.exists():
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("plugins dir %s could not be created: %r", directory, exc)
        return []

    tools: list[ToolDef] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        tools.extend(_load_one(path))
    return tools
