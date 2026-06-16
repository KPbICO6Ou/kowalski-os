"""kow-setup orchestration: per-service local/remote/skip fork, checks, config write.

The config is written ONLY when all configured services pass their checks
(or with accept_warnings=True)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .checks import CheckResult, check_ollama, check_stt, check_tts
from .config import write_conf

SERVICES = ("ollama", "stt", "tts")
WAKE_MODES = ("push_to_talk", "wake_word", "both")
OLLAMA_DEFAULT_PORT = 11434
# Per-service default port appended when the user gives a host with no port.
SERVICE_DEFAULT_PORT = {"ollama": OLLAMA_DEFAULT_PORT, "stt": 5099, "tts": 5000}


def normalize_url(url: str, default_port: int) -> str:
    """Add `http://` when the scheme is missing and `:<default_port>` when no
    port is given. '10.0.0.5' -> 'http://10.0.0.5:<port>'; an explicit port like
    '10.0.0.5:5051' is kept (only the scheme is added)."""
    url = url.strip()
    if not url:
        return url
    if "://" not in url:
        url = "http://" + url
    parsed = urlparse(url)
    if parsed.port is None and parsed.hostname:
        host = parsed.hostname
        if ":" in host:  # IPv6 literal
            host = f"[{host}]"
        netloc = f"{host}:{default_port}"
        if parsed.username:
            cred = parsed.username + (f":{parsed.password}" if parsed.password else "")
            netloc = f"{cred}@{netloc}"
        parsed = parsed._replace(netloc=netloc)
    return urlunparse(parsed).rstrip("/")


def normalize_ollama_url(url: str, default_port: int = OLLAMA_DEFAULT_PORT) -> str:
    """Ollama-specific wrapper around :func:`normalize_url` (default port 11434)."""
    return normalize_url(url, default_port)


@dataclass
class ServiceAnswer:
    mode: str  # local | remote | skip
    url: str = ""
    token: str = ""
    model: str = ""  # ollama only
    language: str = ""  # stt only


def parse_answers(raw: dict) -> dict[str, ServiceAnswer]:
    answers: dict[str, ServiceAnswer] = {}
    for service in SERVICES:
        entry = raw.get(service) or {"mode": "skip"}
        mode = entry.get("mode", "skip")
        if mode not in ("local", "remote", "skip"):
            raise ValueError(f"{service}: invalid mode '{mode}'")
        url = entry.get("url", "")
        if url and service in SERVICE_DEFAULT_PORT:
            url = normalize_url(url, SERVICE_DEFAULT_PORT[service])
        answers[service] = ServiceAnswer(
            mode=mode,
            url=url,
            token=entry.get("token", ""),
            model=entry.get("model", ""),
            language=entry.get("language", ""),
        )
    return answers


def run_checks(answers: dict[str, ServiceAnswer]) -> list[CheckResult]:
    results: list[CheckResult] = []
    for service, answer in answers.items():
        if answer.mode == "skip":
            continue
        if answer.mode == "local":
            # Local installers are phase-0+ work; remote URLs work today.
            from .installers import install_local

            install_local(service)  # raises NotImplementedError with guidance
            continue
        if service == "ollama":
            results.append(check_ollama(answer.url))
        elif service == "stt":
            results.append(check_stt(answer.url, answer.token or None))
        elif service == "tts":
            results.append(check_tts(answer.url, answer.token or None))
    return results


def build_config_updates(answers: dict[str, ServiceAnswer]) -> dict[str, str]:
    updates: dict[str, str] = {}
    ollama = answers["ollama"]
    if ollama.mode != "skip":
        updates["OLLAMA_HOST"] = ollama.url
        if ollama.model:
            updates["OLLAMA_MODEL"] = ollama.model
    stt = answers["stt"]
    if stt.mode != "skip":
        updates["STT_URL"] = stt.url
        if stt.token:
            updates["STT_TOKEN"] = stt.token
        if stt.language:
            updates["STT_LANGUAGE"] = stt.language
    tts = answers["tts"]
    if tts.mode != "skip":
        updates["TTS_URL"] = tts.url
        if tts.token:
            updates["TTS_TOKEN"] = tts.token
    return updates


def build_voice_updates(raw_answers: dict) -> dict[str, str]:
    """Voice activation has no service check — it's pure config. Maps the
    optional `voice` answers section to KOW_WAKE_* keys."""
    voice = raw_answers.get("voice") or {}
    mode = voice.get("wake_mode")
    if mode and mode not in WAKE_MODES:
        raise ValueError(f"voice: invalid wake_mode '{mode}'")
    updates: dict[str, str] = {}
    for key, conf_key in (
        ("wake_mode", "KOW_WAKE_MODE"),
        ("wake_word", "KOW_WAKE_WORD"),
        ("wake_model", "KOW_WAKE_MODEL"),
    ):
        value = voice.get(key)
        if value:
            updates[conf_key] = str(value)
    return updates


def run(raw_answers: dict, config_path: Path, accept_warnings: bool = False) -> tuple[int, list[CheckResult]]:
    """Returns (exit_code, results). Config is written only on success."""
    answers = parse_answers(raw_answers)
    voice_updates = build_voice_updates(raw_answers)  # validate before any checks
    results = run_checks(answers)

    failed = [r for r in results if not r.ok]
    if failed and not accept_warnings:
        return 1, results

    updates = build_config_updates(answers)
    updates.update(voice_updates)
    if updates:
        write_conf(config_path, updates)
    return 0, results
