"""KEY=VALUE config: env > file (~/.config/kowalski/kowalski.conf) > defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("~/.config/kowalski/kowalski.conf").expanduser()

DEFAULTS: dict[str, str] = {
    "OLLAMA_HOST": "http://127.0.0.1:11434",
    "OLLAMA_MODEL": "qwen2.5:7b",
    # LLM transport: "ollama" (native client) or "pydantic-ai" (any provider
    # via pydantic-ai; defaults to the same Ollama host through /v1)
    "KOW_LLM": "ollama",
    # provider-prefixed pydantic-ai model, e.g. "anthropic:claude-sonnet-4-6";
    # empty = wrap OLLAMA_HOST/OLLAMA_MODEL
    "KOW_PAI_MODEL": "",
    # pydantic-ai-toolbox: mount FilesystemToolset as fs.* tools (sandbox = first
    # allowed path); KOW_TOOLBOX_FS_WRITE=1 unlocks write methods (still confirmed)
    "KOW_TOOLBOX_FS": "1",
    "KOW_TOOLBOX_FS_WRITE": "0",
    # Low temperature keeps local models' tool-call markup well-formed
    # (qwen2.5 at default temp occasionally emits unparseable <tool_call> blocks)
    "KOW_TEMPERATURE": "0.2",
    "KOW_DB_PATH": "~/.local/share/kowalski/kowalski.db",
    "KOW_ALLOWED_PATHS": "~",
    "KOW_AUTO_ALLOW_NETWORK": "0",
    "KOW_MAX_ITERATIONS": "8",
    "KOW_TOOL_TIMEOUT": "30",
    "KOW_CONFIRM_TIMEOUT": "120",
    "KOW_SOCKET_PATH": "",
    "KOW_API_ENABLED": "0",
    "KOW_API_PORT": "8377",
    "KOW_LOG_LEVEL": "INFO",
}


def parse_conf(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines; '#' comments and blank lines ignored, quotes stripped."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass
class Config:
    values: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        values = dict(DEFAULTS)
        conf_path = path or DEFAULT_CONFIG_PATH
        if conf_path.exists():
            values.update(parse_conf(conf_path.read_text()))
        for key in values:
            if key in os.environ:
                values[key] = os.environ[key]
        return cls(values)

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    def get_int(self, key: str) -> int:
        return int(self.values[key])

    def get_bool(self, key: str) -> bool:
        return self.values.get(key, "0").lower() in ("1", "true", "yes")

    def get_path(self, key: str) -> Path:
        return Path(self.values[key]).expanduser()

    @property
    def allowed_paths(self) -> list[Path]:
        raw = self.values.get("KOW_ALLOWED_PATHS", "~")
        return [Path(p).expanduser().resolve() for p in raw.split(":") if p]

    @property
    def socket_path(self) -> Path:
        configured = self.values.get("KOW_SOCKET_PATH", "")
        if configured:
            return Path(configured).expanduser()
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if runtime_dir:
            return Path(runtime_dir) / "kowalski.sock"
        state_dir = Path("~/.local/state/kowalski").expanduser()
        return state_dir / "kowalski.sock"
