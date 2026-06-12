"""kow-setup orchestration: per-service local/remote/skip fork, checks, config write.

The config is written ONLY when all configured services pass their checks
(or with accept_warnings=True)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .checks import CheckResult, check_ollama, check_stt, check_tts
from .config import write_conf

SERVICES = ("ollama", "stt", "tts")


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
        answers[service] = ServiceAnswer(
            mode=mode,
            url=entry.get("url", ""),
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


def run(raw_answers: dict, config_path: Path, accept_warnings: bool = False) -> tuple[int, list[CheckResult]]:
    """Returns (exit_code, results). Config is written only on success."""
    answers = parse_answers(raw_answers)
    results = run_checks(answers)

    failed = [r for r in results if not r.ok]
    if failed and not accept_warnings:
        return 1, results

    updates = build_config_updates(answers)
    if updates:
        write_conf(config_path, updates)
    return 0, results
