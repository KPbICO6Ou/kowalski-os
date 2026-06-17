"""Voice configuration.

Resolution order (highest first): environment variables, then the native
ttsgen.conf chain (./ttsgen.conf overriding ~/.config/ttsgen.conf, per the
existing wachawo TTS tooling), then kow-core's kowalski.conf (what `kow-setup`
writes), then defaults. Reads env last because kowalski.config.Config only lifts
env vars for keys it already knows — STT/TTS/wake keys are not among them, so we
parse the file directly here."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

CONF_CHAIN = [Path.home() / ".config" / "ttsgen.conf", Path("ttsgen.conf")]  # later overrides earlier

DEFAULTS = {
    "STT_URL": "http://127.0.0.1:5099",
    "STT_TOKEN": "",
    "STT_LANGUAGE": "",  # empty -> server default
    "TTS_URL": "http://127.0.0.1:5000",
    "TTS_TOKEN": "",
    "TTS_ENGINE": "",  # empty -> server default (ru: silerotts, en: pipertts)
    # Wake activation: how a turn starts.
    #   push_to_talk -> press Enter (no model, works everywhere)
    #   wake_word    -> openWakeWord listens for KOW_WAKE_MODEL/KOW_WAKE_WORD
    #   both         -> Enter OR the wake word, whichever comes first
    "KOW_WAKE_MODE": "push_to_talk",
    # Spoken trigger phrase; used as the openWakeWord model name when
    # KOW_WAKE_MODEL is empty. A custom phrase like "kowalski" needs a trained
    # model file (set KOW_WAKE_MODEL to its .onnx/.tflite path).
    "KOW_WAKE_WORD": "hey_kowalski",
    "KOW_WAKE_MODEL": "",  # path to a custom .onnx/.tflite, or a pretrained name
    "KOW_WAKE_THRESHOLD": "0.5",
    "KOW_VOICE_SAMPLE_RATE": "16000",
    "KOW_VAD_SILENCE_MS": "700",
    "KOW_BARGE_IN": "1",
    "KOW_VOICE_INPUT_DEVICE": "",   # input device name (substring); empty = system default
    "KOW_VOICE_OUTPUT_DEVICE": "",  # TTS output device name (substring); empty = system default
}


def _kowalski_conf_path() -> Path:
    """The kow-core config file that `kow-setup` writes (env KOW_CONFIG wins)."""
    override = os.environ.get("KOW_CONFIG")
    if override:
        return Path(override).expanduser()
    try:
        from kowalski.config import DEFAULT_CONFIG_PATH

        return DEFAULT_CONFIG_PATH
    except Exception:
        return Path("~/.config/kowalski/kowalski.conf").expanduser()


def _parse_conf(path: Path) -> dict[str, str]:
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


@dataclass
class VoiceSettings:
    stt_url: str
    stt_token: str
    stt_language: str
    tts_url: str
    tts_token: str
    tts_engine: str
    wake_mode: str
    wake_word: str
    wake_model: str
    wake_threshold: float
    sample_rate: int
    vad_silence_ms: int
    barge_in: bool
    socket_path: Path
    input_device: str = ""
    output_device: str = ""

    @classmethod
    def load(cls) -> "VoiceSettings":
        values = dict(DEFAULTS)
        # kow-core's kowalski.conf (written by kow-setup) is the lowest layer
        # above the built-in defaults; the native ttsgen.conf chain overrides it.
        values.update(_parse_conf(_kowalski_conf_path()))
        for path in CONF_CHAIN:
            values.update(_parse_conf(path))
        for key in values:
            if key in os.environ:
                values[key] = os.environ[key]

        # kow-core socket path (and any shared keys) come from its own config
        try:
            from kowalski.config import Config

            socket_path = Config.load().socket_path
        except Exception:
            socket_path = Path("~/.local/state/kowalski/kowalski.sock").expanduser()

        return cls(
            stt_url=values["STT_URL"],
            stt_token=values["STT_TOKEN"],
            stt_language=values["STT_LANGUAGE"],
            tts_url=values["TTS_URL"],
            tts_token=values["TTS_TOKEN"],
            tts_engine=values["TTS_ENGINE"],
            wake_mode=values["KOW_WAKE_MODE"],
            wake_word=values["KOW_WAKE_WORD"],
            wake_model=values["KOW_WAKE_MODEL"],
            wake_threshold=float(values["KOW_WAKE_THRESHOLD"]),
            sample_rate=int(values["KOW_VOICE_SAMPLE_RATE"]),
            vad_silence_ms=int(values["KOW_VAD_SILENCE_MS"]),
            barge_in=values["KOW_BARGE_IN"].lower() in ("1", "true", "yes"),
            socket_path=socket_path,
            input_device=values["KOW_VOICE_INPUT_DEVICE"],
            output_device=values["KOW_VOICE_OUTPUT_DEVICE"],
        )
