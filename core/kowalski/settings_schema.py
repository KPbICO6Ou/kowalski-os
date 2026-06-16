"""User-facing settings schema: one source of truth for `kow settings` (TUI)
and `kow setup show|get|set`.

Each Setting maps a short, typeable key (``host``) to the full conf KEY
(``OLLAMA_HOST``) plus a group, an editor kind, and validation. The schema is
deliberately the curated connection/voice surface — every other conf KEY is
still readable/writable by its full UPPER_CASE name."""

from __future__ import annotations

from dataclasses import dataclass

BOOL_TRUE = ("1", "true", "yes", "on")
BOOL_FALSE = ("0", "false", "no", "off")


@dataclass(frozen=True)
class Setting:
    short: str                       # short, typeable key, e.g. "host"
    key: str                         # full conf KEY, e.g. "OLLAMA_HOST"
    group: str                       # display group
    kind: str                        # "text" | "secret" | "bool" | "enum"
    help: str
    choices: tuple[str, ...] = ()    # for kind == "enum"


GROUPS = ("Ollama", "STT", "TTS", "Voice", "Agent")

SETTINGS: tuple[Setting, ...] = (
    Setting("HOST", "OLLAMA_HOST", "Ollama", "text", "Ollama server URL"),
    Setting("MODEL", "OLLAMA_MODEL", "Ollama", "text", "Chat model name"),
    Setting("EMBED", "KOW_EMBED_MODEL", "Ollama", "text", "Embedding model (semantic index)"),
    Setting("VISION", "KOW_VISION", "Ollama", "bool", "Screen vision tools (capture/describe)"),
    Setting("TEMP", "KOW_TEMPERATURE", "Ollama", "text", "Sampling temperature"),
    Setting("STT", "STT_URL", "STT", "text", "Speech-to-text endpoint URL"),
    Setting("STT_TOKEN", "STT_TOKEN", "STT", "secret", "STT auth token"),
    Setting("STT_LANG", "STT_LANGUAGE", "STT", "text", "STT language, e.g. ru / en"),
    Setting("TTS", "TTS_URL", "TTS", "text", "Text-to-speech endpoint URL"),
    Setting("TTS_TOKEN", "TTS_TOKEN", "TTS", "secret", "TTS auth token"),
    Setting("WAKE", "KOW_WAKE_MODE", "Voice", "enum", "How a voice turn starts",
            ("push_to_talk", "wake_word", "both")),
    Setting("WAKE_WORD", "KOW_WAKE_WORD", "Voice", "text", "Wake phrase (openWakeWord name)"),
    Setting("WAKE_MODEL", "KOW_WAKE_MODEL", "Voice", "text", "Path to a custom wake .onnx"),
    Setting("BARGE", "KOW_BARGE_IN", "Voice", "bool", "Allow interrupting the agent (barge-in)"),
    Setting("VOICE_CHAT", "KOW_CHAT_VOICE", "Voice", "bool", "`kow chat` starts in voice mode"),
    Setting("PATHS", "KOW_ALLOWED_PATHS", "Agent", "text", "Allowed filesystem roots (':'-separated)"),
    Setting("LLM", "KOW_LLM", "Agent", "enum", "LLM transport", ("ollama", "pydantic-ai")),
    Setting("MAX_ITER", "KOW_MAX_ITERATIONS", "Agent", "text", "Max agent tool iterations"),
)

BY_SHORT: dict[str, Setting] = {s.short: s for s in SETTINGS}
BY_KEY: dict[str, Setting] = {s.key: s for s in SETTINGS}


def resolve(name: str) -> Setting | None:
    """Match a short key (``HOST``) or a full KEY (``OLLAMA_HOST``), any case."""
    upper = name.upper()
    return BY_KEY.get(upper) or BY_SHORT.get(upper)


def normalize(setting: Setting, value: str) -> str:
    """Validate + canonicalize a value; raise ValueError on a bad value."""
    text = value.strip()
    if setting.kind == "bool":
        if text.lower() in BOOL_TRUE:
            return "1"
        if text.lower() in BOOL_FALSE:
            return "0"
        raise ValueError(f"{setting.short}: expected on/off, got {value!r}")
    if setting.kind == "enum":
        if text not in setting.choices:
            raise ValueError(f"{setting.short}: must be one of {', '.join(setting.choices)}")
        return text
    return text


def is_true(value: str) -> bool:
    return value.strip().lower() in BOOL_TRUE
