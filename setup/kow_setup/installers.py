"""Local installation of Ollama / STT / TTS (docker compose).

Deferred until target hardware exists — the planned commands are documented
here so the wiring is obvious."""

from __future__ import annotations

PLANNED = {
    "ollama": "curl -fsSL https://ollama.com/install.sh | sh && ollama pull <models>",
    "stt": "docker compose -f speech-to-text/docker-compose.yml up -d  # GPU variant if nvidia-container-toolkit",
    "tts": "docker compose -f text-to-speech/docker-compose.yml up -d  # ttssrv on :5000",
}


def install_local(service: str) -> None:
    raise NotImplementedError(
        f"local install of '{service}' is not implemented yet; planned: {PLANNED.get(service)}"
    )
