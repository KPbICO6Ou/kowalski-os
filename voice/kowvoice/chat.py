"""Unified voice + text chat: one conversation you can drive by typing OR by
voice, with every answer printed AND spoken.

Input model (single stdin stream, no concurrency hazards):
  * a non-empty line   -> a text message
  * an empty line (Enter) -> push-to-talk: record from the mic, transcribe (STT)
  * 'exit' / 'quit' / Ctrl-D -> leave

This lives in the voice package because it needs BOTH kow-core (the in-process
agent loop) and the voice adapters (STT/TTS/mic); core delegates here for
`kow chat --voice`. The agent turn is driven through kow-core's `run_turn`, so
typed and spoken turns share one persisted conversation.
"""

from __future__ import annotations

import asyncio
import importlib.util
import uuid

from kowalski.agent.events import TokenEvent
from kowalski.cli import _print_event, _summarize_kwargs
from kowalski.conversations import run_turn

DIM = "\033[2m"
RESET = "\033[0m"


class VoiceChatIO:
    """Real mic->STT input and TTS->speaker output, built lazily from settings.

    Constructing this is cheap (no audio libs touched); sounddevice is only
    imported when recording/playing, so the object is usable in TTS-only setups
    and fails gracefully (caught by the caller) when the [mic] extra is absent."""

    def __init__(self, settings):
        from .audio_devices import EnergyVadRecorder, SoundDeviceSink
        from .stt_http import HttpSttClient
        from .tts_http import HttpTtsClient

        self.settings = settings
        self._recorder = EnergyVadRecorder(settings.sample_rate, settings.vad_silence_ms)
        self._stt = HttpSttClient(settings.stt_url, settings.stt_token)
        self._tts = HttpTtsClient(settings.tts_url, settings.tts_token, settings.tts_engine)
        self._sink = SoundDeviceSink()

    async def record_and_transcribe(self) -> str | None:
        utterance = await self._recorder.record_utterance()
        if utterance is None or utterance.is_empty:
            return None
        transcript = await self._stt.transcribe(
            utterance, language=self.settings.stt_language or None
        )
        return (transcript.text or "").strip() or None

    async def speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        clip = await self._tts.synthesize(text)
        await self._sink.play(clip)


async def run_chat(
    *,
    model: str = "",
    yes: bool = False,
    dry_run: bool = False,
    conversation_id: str | None = None,
    continue_: bool = False,
    speak: bool = True,
    input_fn=input,
    voice_io=None,
) -> int:
    """Run the unified chat loop. `speak` toggles voice I/O; `input_fn`/`voice_io`
    are injectable for tests."""
    from kowalski.agent.loop import AgentLoop
    from kowalski.bootstrap import build_default_registry, build_llm
    from kowalski.config import Config
    from kowalski.conversations import ConversationStore
    from kowalski.policy import AutoConfirm, InteractiveCliConfirmation
    from kowalski.scheduler import ReminderScheduler
    from kowalski.store import Store

    from .settings import VoiceSettings

    try:
        import readline  # noqa: F401  (line editing / history in input())
    except Exception:
        pass

    config = Config.load()
    store = Store(config.get_path("KOW_DB_PATH"))
    scheduler = ReminderScheduler(store)
    confirmer = AutoConfirm() if yes else InteractiveCliConfirmation()
    registry = build_default_registry(config, store, scheduler, confirmer)
    if dry_run:
        registry.dry_run = True
    conversations = ConversationStore(store)

    if continue_ and not conversation_id:
        conversation_id = conversations.last_conversation_id()
    resumed = conversation_id is not None
    if conversation_id is None:
        conversation_id = uuid.uuid4().hex

    if speak and voice_io is None:
        voice_io = VoiceChatIO(VoiceSettings.load())
        if importlib.util.find_spec("sounddevice") is None:
            print(
                f"{DIM}(note: voice input needs the mic extra — "
                f"pip install -e 'voice[mic]'; typing still works){RESET}"
            )

    scheduler.start()
    llm = build_llm(config, model_override=model or "")
    loop = AgentLoop(
        llm,
        registry,
        max_iterations=config.get_int("KOW_MAX_ITERATIONS"),
        context_provider=getattr(registry, "context_provider", None),
    )

    suffix = " (resumed)" if resumed else ""
    mode = "voice + text" if speak else "text"
    print(f"{DIM}kow chat ({mode}) — conversation {conversation_id}{suffix}.{RESET}")
    if speak:
        print(
            f"{DIM}Type a message, or press Enter on an empty line to talk. "
            f"'quit' or Ctrl-D to exit.{RESET}"
        )
        hotkey = config.get("KOW_VOICE_HOTKEY", "").strip() or "Enter (on an empty line)"
        print(f"{DIM}Push-to-talk: {hotkey}{RESET}")
    else:
        print(f"{DIM}Type a message. 'quit' or Ctrl-D to exit.{RESET}")

    try:
        while True:
            try:
                # Synchronous input in the main thread: a run_in_executor() worker
                # blocked on stdin is orphaned on Ctrl-C (SIGINT hits the main
                # thread) and hangs the interpreter's atexit thread join.
                line = input_fn("kow› ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            text = (line or "").strip()
            if text in ("exit", "quit", ":q"):
                break
            if not text:
                if not speak:
                    continue
                print(f"{DIM}[listening…]{RESET}")
                try:
                    text = await voice_io.record_and_transcribe()
                except (KeyboardInterrupt, asyncio.CancelledError):
                    # Ctrl-C while recording cancels just this turn (the mic stream
                    # tears down) — back to the prompt instead of crashing out.
                    print(f"{DIM}(cancelled){RESET}")
                    continue
                except Exception as exc:
                    print(f"{DIM}(voice input failed: {exc}){RESET}")
                    continue
                if not text:
                    print(f"{DIM}(no speech){RESET}")
                    continue
                print(f"{DIM}you (voice):{RESET} {text}")
            answer = await _drive_turn(loop, text, conversation_id, conversations, config)
            if speak and answer:
                try:
                    await voice_io.speak(answer)
                except Exception as exc:
                    print(f"{DIM}(speech output failed: {exc}){RESET}")
    finally:
        scheduler.shutdown()
        store.close()
    print(f"{DIM}(conversation: {conversation_id} — reopen with: kow chat --voice --resume){RESET}")
    return 0


async def run_once(*, model: str = "", speak: bool = True, voice_io=None) -> int:
    """One push-to-talk turn: record a single utterance, answer it (printed and,
    when speak, spoken), then exit. Meant to be bound to a global hotkey.

    Tool confirmations are auto-denied (no GUI on a hotkey turn), so destructive
    actions are blocked by design. `voice_io` is injectable for tests."""
    from kowalski.agent.loop import AgentLoop
    from kowalski.bootstrap import build_default_registry, build_llm
    from kowalski.config import Config
    from kowalski.conversations import ConversationStore
    from kowalski.policy import AutoDeny
    from kowalski.scheduler import ReminderScheduler
    from kowalski.store import Store

    from .settings import VoiceSettings

    config = Config.load()
    store = Store(config.get_path("KOW_DB_PATH"))
    scheduler = ReminderScheduler(store)
    registry = build_default_registry(config, store, scheduler, AutoDeny())
    conversations = ConversationStore(store)
    conversation_id = conversations.last_conversation_id() or uuid.uuid4().hex
    scheduler.start()
    llm = build_llm(config, model_override=model or "")
    loop = AgentLoop(
        llm,
        registry,
        max_iterations=config.get_int("KOW_MAX_ITERATIONS"),
        context_provider=getattr(registry, "context_provider", None),
    )
    if voice_io is None:
        voice_io = VoiceChatIO(VoiceSettings.load())
    try:
        print(f"{DIM}[listening…]{RESET}")
        try:
            text = await voice_io.record_and_transcribe()
        except (KeyboardInterrupt, asyncio.CancelledError):
            print(f"{DIM}(cancelled){RESET}")
            return 0
        except Exception as exc:
            print(f"{DIM}(voice input failed: {exc}){RESET}")
            return 1
        if not text:
            print(f"{DIM}(no speech){RESET}")
            return 0
        print(f"{DIM}you (voice):{RESET} {text}")
        answer = await _drive_turn(loop, text, conversation_id, conversations, config)
        if speak and answer:
            try:
                await voice_io.speak(answer)
            except Exception as exc:
                print(f"{DIM}(speech output failed: {exc}){RESET}")
    finally:
        scheduler.shutdown()
        store.close()
    return 0


async def _drive_turn(loop, text, conversation_id, conversations, config) -> str:
    """Run one agent turn: stream events to the console, return the answer text."""
    parts: list[str] = []
    async for event in run_turn(
        loop, text, conversation_id, conversations, **_summarize_kwargs(config)
    ):
        _print_event(event)
        if isinstance(event, TokenEvent):
            parts.append(event.text)
    return "".join(parts).strip()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="kow-voice chat", description="voice + text chat")
    parser.add_argument("--model", help="override OLLAMA_MODEL")
    parser.add_argument("--yes", action="store_true", help="auto-approve confirmations")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true")
    parser.add_argument("-c", "--conversation", help="conversation ID to resume")
    parser.add_argument("--continue", "--resume", dest="continue_", action="store_true")
    parser.add_argument(
        "--no-speak", dest="speak", action="store_false", help="text only (no mic/TTS)"
    )
    args = parser.parse_args(argv)
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
