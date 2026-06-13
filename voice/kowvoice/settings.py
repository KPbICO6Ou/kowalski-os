"""Voice configuration.

Resolution order (highest first): environment variables, then the native
ttsgen.conf chain (./ttsgen.conf overriding ~/.config/ttsgen.conf, per the
existing wachawo TTS tooling), then kow-core's kowalski.conf, then defaults.
Reads env before kowalski.config.Config because Config only lifts env vars for
keys it already knows."""

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
    "KOW_WAKE_WORD": "hey_kowalski",
    "KOW_VOICE_SAMPLE_RATE": "16000",
    "KOW_VAD_SILENCE_MS": "700",
    "KOW_BARGE_IN": "1",
}


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
    wake_word: str
    sample_rate: int
    vad_silence_ms: int
    barge_in: bool
    socket_path: Path

    @classmethod
    def load(cls) -> "VoiceSettings":
        values = dict(DEFAULTS)
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
            wake_word=values["KOW_WAKE_WORD"],
            sample_rate=int(values["KOW_VOICE_SAMPLE_RATE"]),
            vad_silence_ms=int(values["KOW_VAD_SILENCE_MS"]),
            barge_in=values["KOW_BARGE_IN"].lower() in ("1", "true", "yes"),
            socket_path=socket_path,
        )
