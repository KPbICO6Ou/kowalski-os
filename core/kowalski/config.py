"""KEY=VALUE config: env > file (~/.config/kowalski/kowalski.conf) > defaults."""

from __future__ import annotations

import os
import tempfile
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
    # pydantic-ai-toolbox: mount SystemToolset as read-only system.* host-info tools
    "KOW_TOOLBOX_SYSTEM": "1",
    # Low temperature keeps local models' tool-call markup well-formed
    # (qwen2.5 at default temp occasionally emits unparseable <tool_call> blocks)
    "KOW_TEMPERATURE": "0.2",
    # Phase-5 capabilities (all gated; the risky ones still require confirmation)
    "KOW_VISION": "1",            # screen.capture / screen.describe (READ)
    "KOW_VISION_MODEL": "qwen2.5vl",
    "KOW_UIAUTO": "1",            # windows.* / ui.tree (READ/WRITE) + input.* (DESTRUCTIVE)
    "KOW_SHELL": "1",             # system.run (DESTRUCTIVE, sandboxed on Linux)
    "KOW_SHELL_TIMEOUT": "30",
    "KOW_RECIPES": "1",           # YAML automation recipes
    "KOW_RECIPES_DIR": "",        # empty = ~/.config/kowalski/recipes
    # Long-term memory + personalization (M8): memory.*/profile.* tools and
    # injection of profile facts + recalled memories into the system prompt
    "KOW_MEMORY": "1",
    "KOW_MEMORY_RECALL_K": "5",
    # Long-conversation auto-summarisation: fold turns older than KEEP into a
    # rolling digest once a conversation exceeds AFTER messages
    "KOW_SUMMARIZE": "1",
    "KOW_SUMMARIZE_AFTER": "24",
    "KOW_SUMMARIZE_KEEP": "8",
    # Plugin folder: *.py exporting `TOOLS: list[ToolDef]`; empty = ~/.config/kowalski/plugins
    "KOW_PLUGINS_DIR": "",
    # Visible checklist tools (plan.create/update/show) for multi-step work
    "KOW_CHECKLIST": "1",
    # bluetooth.* / audio.* tools: connect a BT speaker + route audio (needs
    # bluetoothctl + pactl; the tool group is skipped if bluetoothctl is absent)
    "KOW_BLUETOOTH": "1",
    # `kow chat` starts with voice (mic + TTS) on by default; needs the voice
    # package + [mic] extra. --voice/--no-voice override per invocation.
    "KOW_CHAT_VOICE": "0",
    # External MCP servers: "name=cmd arg arg;name2=cmd2 ..." (needs the `mcp` package)
    "KOW_MCP_SERVERS": "",
    # Proactive heartbeat: periodic agent check-in (OFF by default — autonomy)
    "KOW_HEARTBEAT": "0",
    "KOW_HEARTBEAT_INTERVAL_MIN": "30",
    "KOW_DB_PATH": "~/.local/share/kowalski/kowalski.db",
    # semantic index database built by kow-index (the indexer/ package)
    "KOW_INDEX_DB": "~/.local/share/kowalski/index.db",
    # ':'-separated roots for the indexer; empty = fall back to KOW_ALLOWED_PATHS
    "KOW_INDEX_PATHS": "",
    # Ollama embedding model used by the semantic index
    "KOW_EMBED_MODEL": "nomic-embed-text",
    "KOW_ALLOWED_PATHS": "~",
    "KOW_AUTO_ALLOW_NETWORK": "0",
    "KOW_MAX_ITERATIONS": "8",
    "KOW_TOOL_TIMEOUT": "30",
    "KOW_CONFIRM_TIMEOUT": "120",
    "KOW_SOCKET_PATH": "",
    "KOW_API_ENABLED": "0",
    "KOW_API_PORT": "8377",
    "KOW_LOG_LEVEL": "INFO",
    # Mail backend: "mock" (in-memory, no creds — safe dev default) or "imap"
    # (real IMAP/SMTP; requires the 'mail' extra and the keys below)
    "KOW_MAIL_BACKEND": "mock",
    # IMAP (incoming) — secrets belong in the 0600 kowalski.conf, not env/shell
    # history; for Gmail/Outlook use an app-password, not your account password
    "IMAP_HOST": "",
    "IMAP_PORT": "993",
    "IMAP_USER": "",
    "IMAP_PASSWORD": "",
    "IMAP_SSL": "1",
    # SMTP (outgoing) — same advice: keep SMTP_PASSWORD in the 0600 conf file
    "SMTP_HOST": "",
    "SMTP_PORT": "587",
    "SMTP_USER": "",
    "SMTP_PASSWORD": "",
    "SMTP_TLS": "1",
    # From address for sent mail; empty falls back to SMTP_USER
    "MAIL_FROM": "",
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


def write_conf(updates: dict[str, str], path: Path | None = None) -> Path:
    """Merge updates into the conf file atomically; unknown existing keys survive.

    Same on-disk shape kow-setup writes (sorted KEY=VALUE under a header), so the
    wizard, `kow setup set`, and the settings TUI all agree on the format.
    """
    conf_path = path or DEFAULT_CONFIG_PATH
    merged: dict[str, str] = {}
    if conf_path.exists():
        merged = parse_conf(conf_path.read_text())
    merged.update({k: v for k, v in updates.items() if v is not None})
    conf_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"{key}={value}" for key, value in sorted(merged.items())]
    content = "# Kowalski OS configuration (managed by kow-setup)\n" + "\n".join(lines) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=str(conf_path.parent), prefix=".kowalski-conf-")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        os.replace(tmp_name, conf_path)
    except BaseException:
        os.unlink(tmp_name)
        raise
    try:
        conf_path.chmod(0o600)
    except OSError:
        pass
    return conf_path


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
