"""KEY=VALUE config read/write: atomic, preserves unknown keys and comments-on-own-lines."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

MANAGED_KEYS = (
    "OLLAMA_HOST",
    "OLLAMA_MODEL",
    "STT_URL",
    "STT_TOKEN",
    "STT_LANGUAGE",
    "TTS_URL",
    "TTS_TOKEN",
)


def read_conf(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def write_conf(path: Path, updates: dict[str, str]) -> None:
    """Merge updates into the file atomically; unknown existing keys survive."""
    merged = read_conf(path)
    merged.update({k: v for k, v in updates.items() if v is not None})
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"{key}={value}" for key, value in sorted(merged.items())]
    content = "# Kowalski OS configuration (managed by kow-setup)\n" + "\n".join(lines) + "\n"

    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".kowalski-conf-")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    except BaseException:
        os.unlink(tmp_name)
        raise
    os.chmod(path, 0o600)
