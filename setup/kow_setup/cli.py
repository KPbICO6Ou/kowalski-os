"""kow-setup CLI: interactive prompts or --non-interactive --answers FILE."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from . import __version__
from .core import SERVICES, run

DEFAULT_CONFIG = Path("~/.config/kowalski/kowalski.conf").expanduser()


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
        raw = ask_interactively()

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


def ask_interactively() -> dict:
    raw: dict = {}
    print("Kowalski OS setup — for each service choose: remote URL or skip.")
    print("(local install is not available yet)\n")
    for service in SERVICES:
        mode = input(f"{service}: [r]emote / [s]kip? ").strip().lower()
        if mode.startswith("r"):
            url = input(f"  {service} URL: ").strip()
            entry: dict = {"mode": "remote", "url": url}
            if service in ("stt", "tts"):
                token = input("  token (optional): ").strip()
                if token:
                    entry["token"] = token
            if service == "ollama":
                model = input("  model (optional, e.g. qwen2.5:14b): ").strip()
                if model:
                    entry["model"] = model
            if service == "stt":
                language = input("  language (ru/en/auto, optional): ").strip()
                if language:
                    entry["language"] = language
            raw[service] = entry
        else:
            raw[service] = {"mode": "skip"}

    voice = ask_voice()
    if voice:
        raw["voice"] = voice
    return raw


def ask_voice() -> dict:
    """Optional wake-activation prompt (push-to-talk / wake word / both)."""
    print("\nVoice activation (optional):")
    choice = input(
        "  wake mode [p]ush-to-talk / [w]ake-word / [b]oth / [s]kip? "
    ).strip().lower()
    if not choice or choice.startswith("s"):
        return {}
    mode = {"p": "push_to_talk", "w": "wake_word", "b": "both"}.get(choice[0])
    if mode is None:
        return {}
    voice: dict = {"wake_mode": mode}
    if mode in ("wake_word", "both"):
        word = input(
            "  wake word (pretrained name) or path to a .onnx/.tflite model "
            "[hey_kowalski]: "
        ).strip()
        if word:
            key = "wake_model" if any(s in word for s in (".onnx", ".tflite", "/")) else "wake_word"
            voice[key] = word
    return voice


if __name__ == "__main__":
    sys.exit(main())
