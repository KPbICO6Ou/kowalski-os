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
    kind: str                        # text | secret | bool | enum | model | hotkey
    help: str
    choices: tuple[str, ...] = ()    # for kind == "enum"


GROUPS = ("Ollama", "STT", "TTS", "Voice", "Agent")

SETTINGS: tuple[Setting, ...] = (
    Setting("ollama_host", "OLLAMA_HOST", "Ollama", "text", "Ollama server URL"),
    Setting("ollama_model", "OLLAMA_MODEL", "Ollama", "model", "Chat model name"),
    Setting("kow_embed_model", "KOW_EMBED_MODEL", "Ollama", "model", "Embedding model (semantic index)"),
    Setting("kow_vision", "KOW_VISION", "Ollama", "bool", "Screen vision tools (capture/describe)"),
    Setting("kow_temperature", "KOW_TEMPERATURE", "Ollama", "text", "Sampling temperature"),
    Setting("stt_url", "STT_URL", "STT", "text", "Speech-to-text endpoint URL"),
    Setting("stt_token", "STT_TOKEN", "STT", "secret", "STT auth token"),
    Setting("stt_language", "STT_LANGUAGE", "STT", "text", "STT language, e.g. ru / en"),
    Setting("tts_url", "TTS_URL", "TTS", "text", "Text-to-speech endpoint URL"),
    Setting("tts_token", "TTS_TOKEN", "TTS", "secret", "TTS auth token"),
    Setting("tts_language", "TTS_LANGUAGE", "TTS", "text",
            "TTS voice language, e.g. ru / en (empty = follow STT language / server default)"),
    Setting("kow_wake_mode", "KOW_WAKE_MODE", "Voice", "enum", "How a voice turn starts",
            ("push_to_talk", "wake_word", "both")),
    Setting("kow_wake_word", "KOW_WAKE_WORD", "Voice", "text", "Wake phrase (openWakeWord name)"),
    Setting("kow_wake_model", "KOW_WAKE_MODEL", "Voice", "text", "Path to a custom wake .onnx"),
    Setting("kow_barge_in", "KOW_BARGE_IN", "Voice", "bool", "Allow interrupting the agent (barge-in)"),
    Setting("kow_chat_voice", "KOW_CHAT_VOICE", "Voice", "bool", "`kow chat` starts in voice mode"),
    Setting("kow_voice_hotkey", "KOW_VOICE_HOTKEY", "Voice", "hotkey",
            "Push-to-talk key — in the TUI press Enter to capture, Esc to cancel"),
    Setting("kow_voice_input_device", "KOW_VOICE_INPUT_DEVICE", "Voice", "mic",
            "Microphone — Enter opens a picker with a live level meter + echo test"),
    Setting("kow_voice_output_device", "KOW_VOICE_OUTPUT_DEVICE", "Voice", "speaker",
            "TTS output — Enter opens a picker with a test tone"),
    Setting("kow_allowed_paths", "KOW_ALLOWED_PATHS", "Agent", "text", "Allowed filesystem roots (':'-separated)"),
    Setting("kow_llm", "KOW_LLM", "Agent", "enum", "LLM transport", ("ollama", "pydantic-ai")),
    Setting("kow_max_iterations", "KOW_MAX_ITERATIONS", "Agent", "text", "Max agent tool iterations"),
)

BY_SHORT: dict[str, Setting] = {s.short: s for s in SETTINGS}
BY_KEY: dict[str, Setting] = {s.key: s for s in SETTINGS}


def resolve(name: str) -> Setting | None:
    """Match a short key (``host``) or a full KEY (``OLLAMA_HOST``), any case."""
    return BY_KEY.get(name.upper()) or BY_SHORT.get(name.lower())


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
