"""kow-setup CLI: interactive prompts or --non-interactive --answers FILE."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from . import __version__
from .config import read_conf
from .core import SERVICES, normalize_ollama_url, run

DEFAULT_CONFIG = Path("~/.config/kowalski/kowalski.conf").expanduser()

# config key holding each service's URL — used to pre-fill the wizard defaults
SERVICE_URL_KEY = {"ollama": "OLLAMA_HOST", "stt": "STT_URL", "tts": "TTS_URL"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kow-setup", description="Kowalski OS first-run setup")
    parser.add_argument("--version", action="version", version=f"kow-setup {__version__}")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--answers", type=Path, help="answers YAML (required with --non-interactive)")
    parser.add_argument("--accept-warnings", action="store_true",
                        help="write config even if checks fail")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help=f"config path (default: {DEFAULT_CONFIG})")
    args = parser.parse_args(argv)

    if args.non_interactive:
        if not args.answers:
            parser.error("--non-interactive requires --answers FILE")
        raw = yaml.safe_load(args.answers.read_text()) or {}
    else:
        raw = ask_interactively(read_conf(args.config))

    try:
        code, results = run(raw, args.config, accept_warnings=args.accept_warnings)
    except NotImplementedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    for result in results:
        status = "OK " if result.ok else "FAIL"
        latency = f"{result.latency_ms} ms" if result.latency_ms is not None else "-"
        extra = result.error or result.detail
        print(f"[{status}] {result.service:<7} {latency:>8}  {extra}")

    if code == 0:
        print(f"config written: {args.config}")
    else:
        print("checks failed; config NOT written (use --accept-warnings to override)",
              file=sys.stderr)
    return code


def _hint(value: str) -> str:
    """' [value]' suffix shown when there is a current value to keep on Enter."""
    return f" [{value}]" if value else ""


def _default_mode(service: str, current: dict) -> str:
    """A service already configured defaults to 'remote', otherwise 'skip'."""
    return "r" if current.get(SERVICE_URL_KEY[service]) else "s"


def ask_interactively(current: dict | None = None) -> dict:
    """Interactive wizard. `current` (the existing config) pre-fills the prompts
    so pressing Enter keeps the configured value."""
    current = current or {}
    raw: dict = {}
    print("Kowalski OS setup — for each service choose: remote URL or skip.")
    print("(local install is not available yet; Enter keeps the current value)\n")
    for service in SERVICES:
        default = _default_mode(service, current)
        mode = input(f"{service}: [r]emote / [s]kip? [{default}] ").strip().lower() or default
        if not mode.startswith("r"):
            raw[service] = {"mode": "skip"}
            continue
        raw[service] = (
            ask_ollama(current) if service == "ollama" else ask_http_service(service, current)
        )

    voice = ask_voice(current)
    if voice:
        raw["voice"] = voice
    return raw


def ask_http_service(service: str, current: dict | None = None) -> dict:
    """Prompt for an STT/TTS remote endpoint (URL + optional token/language)."""
    current = current or {}
    cur_url = current.get(SERVICE_URL_KEY[service], "")
    url = input(f"  {service} URL{_hint(cur_url)}: ").strip() or cur_url
    entry: dict = {"mode": "remote", "url": url}
    # A blank token leaves any configured token untouched (write_conf preserves it).
    has_token = bool(current.get(f"{service.upper()}_TOKEN"))
    token_prompt = "  token (blank = keep current): " if has_token else "  token (optional): "
    token = input(token_prompt).strip()
    if token:
        entry["token"] = token
    if service == "stt":
        cur_lang = current.get("STT_LANGUAGE", "")
        language = input(f"  language (ru/en/auto, optional){_hint(cur_lang)}: ").strip() or cur_lang
        if language:
            entry["language"] = language
    return entry


def ask_ollama(current: dict | None = None) -> dict:
    """Prompt for the Ollama URL, probe it (default port 11434 when omitted),
    then offer the server's installed models to pick from. Pre-fills from the
    current config."""
    current = current or {}
    cur_url = current.get("OLLAMA_HOST", "")
    cur_model = current.get("OLLAMA_MODEL", "")
    entry: dict = {"mode": "remote"}
    while True:
        raw_url = input(f"  ollama URL (host[:port], default port 11434){_hint(cur_url)}: ").strip()
        url = normalize_ollama_url(raw_url or cur_url)
        if not url:
            print("  (please enter a URL)")
            continue
        from .checks import check_ollama  # imported here so tests can patch it

        result = check_ollama(url)
        if result.ok:
            models = [m for m in result.detail.get("models", []) if m]
            print(f"  [OK] {url} — {result.latency_ms} ms, {len(models)} model(s)")
            entry["url"] = url
            model = _choose_model(models, cur_model)
            if model:
                entry["model"] = model
            return entry
        print(f"  [unreachable] {url} — {result.error}")
        if input("  re-enter URL? [Y/n]: ").strip().lower().startswith("n"):
            entry["url"] = url
            model = input(f"  model (type it, optional){_hint(cur_model)}: ").strip() or cur_model
            if model:
                entry["model"] = model
            return entry


def _choose_model(models: list[str], current: str = "") -> str:
    """Show the installed models and return the chosen name. Accepts a list
    number or a typed name; blank keeps the current model (or the server default
    when none is configured). The current model is flagged in the list."""
    if not models:
        print("  (no models installed on the server)")
        return input(f"  model (type it, optional){_hint(current)}: ").strip() or current
    print("  available models:")
    for index, name in enumerate(models, start=1):
        marker = "  (current)" if name == current else ""
        print(f"    {index}) {name}{marker}")
    keep = "keep current" if current else "server default"
    choice = input(f"  choose [number or name, blank = {keep}]: ").strip()
    if not choice:
        return current
    if choice.isdigit():
        position = int(choice) - 1
        if 0 <= position < len(models):
            return models[position]
        print(f"  (no #{choice}; using it as a literal name)")
    return choice


def ask_voice(current: dict | None = None) -> dict:
    """Optional wake-activation prompt (push-to-talk / wake word / both). Blank
    leaves the current wake config untouched."""
    current = current or {}
    cur_mode = current.get("KOW_WAKE_MODE", "")
    letter = {"push_to_talk": "p", "wake_word": "w", "both": "b"}.get(cur_mode, "")
    print("\nVoice activation (optional):")
    prompt = "  wake mode [p]ush-to-talk / [w]ake-word / [b]oth / [s]kip?"
    choice = input(f"{prompt}{_hint(letter)} ").strip().lower()
    if not choice or choice.startswith("s"):
        return {}  # leave the configured wake mode as-is
    mode = {"p": "push_to_talk", "w": "wake_word", "b": "both"}.get(choice[0])
    if mode is None:
        return {}
    voice: dict = {"wake_mode": mode}
    if mode in ("wake_word", "both"):
        cur_word = current.get("KOW_WAKE_MODEL") or current.get("KOW_WAKE_WORD") or "hey_kowalski"
        word = input(
            f"  wake word (pretrained name) or path to a .onnx/.tflite model [{cur_word}]: "
        ).strip() or cur_word
        if word:
            key = "wake_model" if any(s in word for s in (".onnx", ".tflite", "/")) else "wake_word"
            voice[key] = word
    return voice


if __name__ == "__main__":
    sys.exit(main())
