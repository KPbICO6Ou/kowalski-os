"""kow-voice CLI.

  kow-voice demo [--barge-in]   run the whole pipeline with mocks (any OS)
  kow-voice run                 real pipeline (mic + STT/TTS services + kow-core)
  kow-voice check               probe STT, TTS, and the kow-core socket
  kow-voice test                round-trip self-test (greet → record → STT → echo)
  kow-voice chat                voice + text chat in one conversation
  kow-voice train <phrase>      prepare a custom wake word
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from . import __version__
from .settings import VoiceSettings
from .types import VoiceEvent

ICONS = {
    "idle": "·",
    "listening": "🎙",
    "transcribing": "✍",
    "thinking": "🤔",
    "speaking": "🔊",
}


def _print_event(event: VoiceEvent) -> None:
    if event.kind == "state":
        print(f"  [{event.state}] {ICONS.get(event.state, '')}")
    elif event.kind == "ready":
        print("voice pipeline ready")
    elif event.kind == "transcript":
        print(f"  heard: “{event.text}”")
    elif event.kind == "speak":
        print(f"  🔊 {event.text}")
    elif event.kind == "answer":
        print(f"  answer: {event.text}")
    elif event.kind == "barge_in":
        print("  ⚡ barge-in — user interrupted")
    elif event.kind == "no_speech":
        print("  (no speech)")
    elif event.kind == "error":
        print(f"  error: {event.text}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kow-voice", description="Kowalski OS voice pipeline")
    parser.add_argument("--version", action="version", version=f"kow-voice {__version__}")
    sub = parser.add_subparsers(dest="command")

    demo = sub.add_parser("demo", help="run the pipeline with mocks (no hardware)")
    demo.add_argument("--barge-in", action="store_true", help="simulate a mid-answer interruption")

    sub.add_parser("run", help="real pipeline (mic + STT/TTS + kow-core)")
    sub.add_parser("check", help="probe STT/TTS/kow-core connectivity")
    sub.add_parser(
        "test", help="round-trip self-test: greet → record → STT → echo (LLM diagnosis on failure)"
    )

    train = sub.add_parser("train", help="prepare a custom wake word (register a model or train)")
    train.add_argument("phrase", help="wake phrase, e.g. kowalski or hey_jarvis")
    train.add_argument("--model", help="path to an already-trained .onnx/.tflite model")
    train.add_argument("--out-dir", type=Path, dest="out_dir", help="where to store the model")

    chat = sub.add_parser("chat", help="voice + text chat (type or talk; answers printed + spoken)")
    chat.add_argument("--model", help="override OLLAMA_MODEL")
    chat.add_argument("--yes", action="store_true", help="auto-approve confirmations")
    chat.add_argument("--dry-run", dest="dry_run", action="store_true")
    chat.add_argument("-c", "--conversation", help="conversation ID to resume")
    chat.add_argument("--continue", "--resume", dest="continue_", action="store_true")
    chat.add_argument("--no-speak", dest="speak", action="store_false", help="text only (no mic/TTS)")

    args = parser.parse_args(argv)
    if args.command == "demo":
        return asyncio.run(cmd_demo(barge_in=args.barge_in))
    if args.command == "run":
        return asyncio.run(cmd_run())
    if args.command == "check":
        return asyncio.run(cmd_check())
    if args.command == "test":
        from .selftest import run_test

        return asyncio.run(run_test())
    if args.command == "train":
        from .train import run_train

        return run_train(args.phrase, model=args.model, out_dir=args.out_dir)
    if args.command == "chat":
        from .chat import run_chat

        return asyncio.run(
            run_chat(
                model=args.model or "",
                yes=args.yes,
                dry_run=args.dry_run,
                conversation_id=args.conversation,
                continue_=args.continue_,
                speak=args.speak,
            )
        )
    parser.print_help()
    return 1


async def cmd_demo(barge_in: bool) -> int:
    from .mocks import (
        MockAgentSession,
        MockAudioSink,
        MockInterrupter,
        MockRecorder,
        MockSttClient,
        MockTtsClient,
        MockWakeListener,
        silent_utterance,
    )
    from .orchestrator import VoiceOrchestrator

    settings = VoiceSettings.load()
    settings.barge_in = barge_in
    interrupter = MockInterrupter()

    on_synthesize = None
    utterances = [silent_utterance()]
    transcripts = ["what's the weather like today?"]
    if barge_in:
        # interrupt while the second sentence is being synthesized, then the
        # user says something new which the pipeline picks up
        on_synthesize = lambda _text, n: interrupter.trigger() if n == 2 else None  # noqa: E731
        utterances.append(silent_utterance())
        transcripts.append("actually, never mind")

    orchestrator = VoiceOrchestrator(
        wake=MockWakeListener(fires=1),
        recorder=MockRecorder(utterances),
        stt=MockSttClient(transcripts),
        agent=MockAgentSession(
            ["Today it is ", "sunny and warm. ", "A light breeze ", "in the afternoon."]
        ),
        tts=MockTtsClient(on_synthesize=on_synthesize),
        sink=MockAudioSink(),
        interrupter=interrupter,
        settings=settings,
        on_event=_print_event,
    )
    await orchestrator.run_once()
    print("demo complete")
    return 0


def _build_real_pipeline(settings: VoiceSettings):
    from .agent_socket import SocketAgentSession
    from .audio_devices import EnergyVadRecorder, SoundDeviceSink, build_wake
    from .mocks import MockInterrupter  # barge-in mic monitor is a future upgrade
    from .stt_http import HttpSttClient
    from .tts_http import HttpTtsClient
    from .orchestrator import VoiceOrchestrator

    return VoiceOrchestrator(
        wake=build_wake(settings),
        recorder=EnergyVadRecorder(settings.sample_rate, settings.vad_silence_ms),
        stt=HttpSttClient(settings.stt_url, settings.stt_token),
        agent=SocketAgentSession(settings.socket_path),
        tts=HttpTtsClient(settings.tts_url, settings.tts_token, settings.tts_engine),
        sink=SoundDeviceSink(),
        interrupter=MockInterrupter(),
        settings=VoiceSettings(**{**settings.__dict__, "barge_in": False}),
        on_event=_print_event,
    )


def _require_mic() -> str | None:
    """Return an error string if the [mic] audio stack is missing, else None."""
    import importlib.util

    missing = [m for m in ("sounddevice", "numpy") if importlib.util.find_spec(m) is None]
    if missing:
        return (
            f"voice hardware stack unavailable (missing: {', '.join(missing)}). "
            "Install the mic extra: pip install -e 'voice[mic]'"
        )
    return None


async def cmd_run() -> int:
    settings = VoiceSettings.load()
    err = _require_mic()
    if err:
        print(err, file=sys.stderr)
        return 2
    if settings.wake_mode.lower() in ("wake_word", "both"):
        import importlib.util

        if importlib.util.find_spec("openwakeword") is None:
            print(
                "wake word needs openWakeWord (in the mic extra): "
                "pip install -e 'voice[mic]'",
                file=sys.stderr,
            )
            return 2
    try:
        orchestrator = _build_real_pipeline(settings)
    except ImportError as exc:
        print(
            f"voice hardware stack unavailable ({exc}). "
            "Install the mic extra: pip install -e 'voice[mic]'",
            file=sys.stderr,
        )
        return 2
    print(f"kow-voice running — wake mode: {settings.wake_mode} (Ctrl-C to stop)")
    try:
        await orchestrator.run()
    except KeyboardInterrupt:
        orchestrator.stop()
    return 0


async def cmd_check() -> int:
    from .stt_http import HttpSttClient
    from .tts_http import HttpTtsClient

    settings = VoiceSettings.load()
    ok = True

    for name, client in (
        ("STT", HttpSttClient(settings.stt_url, settings.stt_token, timeout=5.0)),
        ("TTS", HttpTtsClient(settings.tts_url, settings.tts_token, timeout=5.0)),
    ):
        try:
            health = await client.health()
            print(f"[OK]   {name:4} {client.url} — {health}")
        except Exception as exc:
            ok = False
            print(f"[FAIL] {name:4} {client.url} — {exc}")

    try:
        reader, writer = await asyncio.open_unix_connection(str(settings.socket_path))
        writer.write(b'{"op": "status"}\n')
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=5)
        writer.close()
        print(f"[OK]   core {settings.socket_path} — {line.decode().strip()}")
    except Exception as exc:
        ok = False
        print(f"[FAIL] core {settings.socket_path} — {exc}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
