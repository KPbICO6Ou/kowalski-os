"""Index settings on top of kowalski.config.Config.

Core may not define the KOW_INDEX_* keys in its DEFAULTS yet, and Config.load()
only picks env vars for known keys, so every accessor checks the environment
first, then the config file values, then a local default.
"""

from __future__ import annotations

import os
from pathlib import Path

from kowalski.config import Config

DEFAULT_DB_PATH = "~/.local/share/kowalski/index.db"
DEFAULT_MODEL = "nomic-embed-text"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"


def _get(config: Config, key: str, default: str = "") -> str:
    return os.environ.get(key) or config.get(key) or default


def db_path(config: Config) -> Path:
    return Path(_get(config, "KOW_INDEX_DB", DEFAULT_DB_PATH)).expanduser()


def index_paths(config: Config) -> list[Path]:
    """KOW_INDEX_PATHS (colon-separated); empty -> fall back to KOW_ALLOWED_PATHS."""
    raw = _get(config, "KOW_INDEX_PATHS") or _get(config, "KOW_ALLOWED_PATHS", "~")
    return [Path(p).expanduser() for p in raw.split(":") if p]


def embed_model(config: Config) -> str:
    return _get(config, "KOW_EMBED_MODEL", DEFAULT_MODEL)


def ollama_host(config: Config) -> str:
    return _get(config, "OLLAMA_HOST", DEFAULT_OLLAMA_HOST)
