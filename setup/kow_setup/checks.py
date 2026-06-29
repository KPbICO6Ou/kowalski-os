"""Level-1 connectivity checks for Ollama / STT / TTS.

Pure functions over HTTP; kow-setup core consumes only CheckResult, so these
internals can later be swapped for `wtf audit --check ... --format json`
(wtftools) without touching the rest."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import requests

TIMEOUT = 5.0


@dataclass
class CheckResult:
    service: str
    ok: bool
    latency_ms: int | None = None
    detail: dict = field(default_factory=dict)
    error: str | None = None


def _get(url: str, token: str | None = None) -> tuple[dict, int]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    started = time.perf_counter()
    response = requests.get(url, headers=headers, timeout=TIMEOUT)
    latency_ms = int((time.perf_counter() - started) * 1000)
    response.raise_for_status()
    return response.json(), latency_ms


def check_ollama(url: str) -> CheckResult:
    try:
        payload, latency = _get(f"{url.rstrip('/')}/api/tags")
    except Exception as exc:
        return CheckResult(service="ollama", ok=False, error=str(exc))
    models = [m.get("name") for m in payload.get("models", [])]
    return CheckResult(
        service="ollama", ok=True, latency_ms=latency, detail={"models": models}
    )


def check_stt(url: str, token: str | None = None) -> CheckResult:
    try:
        payload, latency = _get(f"{url.rstrip('/')}/api/health", token)
    except Exception as exc:
        return CheckResult(service="stt", ok=False, error=str(exc))
    available = payload.get("available", 0)
    ok = bool(available)
    return CheckResult(
        service="stt", ok=ok, latency_ms=latency, detail=payload,
        error=None if ok else "no STT workers available",
    )


def check_tts(url: str, token: str | None = None) -> CheckResult:
    try:
        payload, latency = _get(f"{url.rstrip('/')}/api/health", token)
    except Exception as exc:
        return CheckResult(service="tts", ok=False, error=str(exc))
    return CheckResult(service="tts", ok=True, latency_ms=latency, detail=payload)


def check_imap(host: str, port: int, user: str, password: str, ssl: bool = True) -> CheckResult:
    """Log in to the IMAP server and list folders. Needs the 'mail' extra
    (imap_tools); reports a clear error when it isn't installed."""
    try:
        from imap_tools import MailBox, MailBoxUnencrypted
    except ImportError:
        return CheckResult(
            service="mail", ok=False,
            error="the 'mail' extra isn't installed (pip install 'kowalski[mail]')",
        )
    try:
        started = time.perf_counter()
        box_cls = MailBox if ssl else MailBoxUnencrypted
        with box_cls(host, port=port).login(user, password) as box:
            folders = [f.name for f in box.folder.list()]
        latency_ms = int((time.perf_counter() - started) * 1000)
        return CheckResult(service="mail", ok=True, latency_ms=latency_ms,
                           detail={"folders": folders})
    except Exception as exc:
        return CheckResult(service="mail", ok=False, error=str(exc))
