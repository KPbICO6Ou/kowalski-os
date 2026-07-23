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
from kowalski.agent.render import print_event, summarize_kwargs
from kowalski.conversations import run_turn

from .console import DIM, RESET, Work, mic_meter
from .term_input import TALK, fmt_hotkey, hotkey_bytes, raw_read, reader_for
from .voice_io import VoiceChatIO


def build_chat_wake(settings):
    """An openWakeWord listener for in-chat hands-free activation, or None when
    the wake word isn't configured/available. Unlike `build_wake`, this is the
    spoken-word listener ALONE — the chat loop already owns Enter/the hotkey, so
    pairing it with PushToTalkWake (which reads stdin too) would clash."""
    import importlib.util

    mode = (getattr(settings, "wake_mode", "") or "").lower()
    model = settings.wake_model or settings.wake_word
    if mode not in ("wake_word", "both") or not model:
        return None
    if importlib.util.find_spec("openwakeword") is None:
        return None
    try:
        from .audio_devices import OpenWakeWordListener

        return OpenWakeWordListener(model, settings.sample_rate, settings.wake_threshold,
                                    device=settings.input_device)
    except Exception:
        return None


async def read_or_wake(loop_ev, reader, wake):
    """Race a cancellable raw read (reader(stop)) against wake.wait_for_wake().
    Returns the reader's result, or TALK when the wake word fires first. Either
    way the loser is cancelled cleanly (no orphaned mic/stdin worker)."""
    import contextlib
    import threading

    stop = threading.Event()
    read_task = loop_ev.run_in_executor(None, reader, stop)
    wake_task = asyncio.ensure_future(wake.wait_for_wake())
    try:
        await asyncio.wait({read_task, wake_task}, return_when=asyncio.FIRST_COMPLETED)
    except (KeyboardInterrupt, asyncio.CancelledError):
        stop.set()
        wake_task.cancel()
        for t in (read_task, wake_task):
            with contextlib.suppress(BaseException):
                await t
        raise
    if wake_task.done() and not wake_task.cancelled() and wake_task.exception() is None:
        stop.set()  # unblock the reader thread so it exits
        with contextlib.suppress(BaseException):
            await read_task
        return TALK
    # typing won, or the wake listener errored. Surface an error (otherwise the
    # word silently stops working — e.g. the mic device failed to open) instead of
    # swallowing it; a clean cancellation is not an error.
    if wake_task.done() and not wake_task.cancelled() and wake_task.exception() is not None:
        import sys

        exc = wake_task.exception()
        if not getattr(wake, "warned", False):  # once, so a broken mic isn't invisible
            wake.warned = True
            print(f"\r{DIM}wake word off — listener stopped: {type(exc).__name__}: {exc}{RESET}",
                  file=sys.stderr, flush=True)
    wake_task.cancel()  # drop the listener
    with contextlib.suppress(BaseException):
        await wake_task
    return await read_task  # awaits typing if wake errored first; re-raises EOF/etc.


async def run_chat(
    *,
    model: str = "",
    yes: bool = False,
    dry_run: bool = False,
    conversation_id: str | None = None,
    continue_: bool = False,
    speak: bool = True,
    input_fn=None,
    voice_io=None,
    wake=None,
) -> int:
    """Run the unified chat loop. `speak` toggles voice I/O; `input_fn`/`voice_io`/
    `wake` are injectable for tests. With no input_fn, a tty + a usable
    KOW_VOICE_HOTKEY switches to a raw-mode reader so the hotkey can start a turn;
    when the wake word is configured (KOW_WAKE_MODE wake_word/both), saying it
    starts a turn too — raced against typing on a real terminal."""
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

    vsettings = VoiceSettings.load() if speak else None
    if speak and voice_io is None:
        voice_io = VoiceChatIO(vsettings)
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

    # Input setup. The wake word and the hotkey both need raw cbreak mode (so the
    # read is cancellable / hotkey-aware); a cooked input() can't be raced, so it
    # disables the wake word.
    import sys

    raw_hotkey = None
    if input_fn is None and speak and sys.stdin.isatty():
        raw_hotkey = hotkey_bytes(config.get("KOW_VOICE_HOTKEY", ""))
        if wake is None:
            wake = build_chat_wake(vsettings)
        if raw_hotkey is not None or wake is not None:
            input_fn = reader_for(raw_hotkey)
    if input_fn is None:
        input_fn = input  # cooked input() keeps readline history/editing
        wake = None        # can't race a cooked, uncancellable input()

    suffix = " (resumed)" if resumed else ""
    mode = "voice + text" if speak else "text"
    print(f"{DIM}kow chat ({mode}) — conversation {conversation_id}{suffix}.{RESET}")
    if speak:
        hk = config.get("KOW_VOICE_HOTKEY", "").strip()
        triggers = ["press Enter on an empty line"]
        if hk:
            triggers.append(fmt_hotkey(hk))
        if wake is not None:
            triggers.append(f"say “{vsettings.wake_word or vsettings.wake_model}”")
        print(
            f"{DIM}Type a message, or {' / '.join(triggers)} to talk. "
            f"'quit' or Ctrl-D to exit.{RESET}"
        )
    else:
        print(f"{DIM}Type a message. 'quit' or Ctrl-D to exit.{RESET}")

    # A green ● marks the wake listener as armed (listening for the word). An
    # emoji like 🎙 doesn't render in every terminal, so use a basic symbol.
    prompt = "\033[32m●\033[0m kow› " if wake is not None else "kow› "
    try:
        while True:
            try:
                if wake is not None:
                    # Race typing against the wake word; the raw reader polls so
                    # it can be cancelled when the word fires (no orphaned worker).
                    line = await read_or_wake(
                        asyncio.get_event_loop(),
                        lambda stop: raw_read(prompt, raw_hotkey, stop=stop),
                        wake,
                    )
                else:
                    # Synchronous input in the main thread: a run_in_executor()
                    # worker blocked on stdin is orphaned on Ctrl-C (SIGINT hits the
                    # main thread) and hangs the interpreter's atexit thread join.
                    line = input_fn(prompt)
            except (EOFError, KeyboardInterrupt):
                print()
                break
            by_voice = line is TALK  # hands-free trigger (hotkey / wake word)
            if by_voice:
                text = ""
            else:
                text = (line or "").strip()
                if text in ("exit", "quit", ":q"):
                    break
            if not text:
                if not speak:
                    continue
                if by_voice:
                    if getattr(vsettings, "raise_window", True):
                        # bring this terminal to the foreground (best-effort X11)
                        from .desktop import raise_own_window
                        await asyncio.get_event_loop().run_in_executor(None, raise_own_window)
                    await voice_io.play_cue()  # earcon: mic is now listening
                # Inline indicator on the input line; \r + clear-to-EOL (\033[K)
                # overwrites it in place with the result (or the cancel/error).
                print(f"{DIM}🎤 listening… (speak; silence ends it){RESET}", end="", flush=True)
                try:
                    utterance = await voice_io.record(on_level=mic_meter)
                except (KeyboardInterrupt, asyncio.CancelledError):
                    # Ctrl-C while recording cancels just this turn (the mic stream
                    # tears down) — back to the prompt instead of crashing out.
                    print(f"\r{DIM}(cancelled){RESET}\033[K")
                    continue
                except Exception as exc:
                    print(f"\r{DIM}(voice input failed: {exc}){RESET}\033[K")
                    continue
                if utterance is None or utterance.is_empty:
                    print(f"\r{DIM}(no speech){RESET}\033[K")
                    continue
                try:
                    async with Work("STT") as w:  # dots while the network STT runs
                        text = await voice_io.transcribe(utterance)
                        w.chars = len(text or "")
                except Exception as exc:
                    print(f"\r{DIM}(transcription failed: {exc}){RESET}\033[K")
                    continue
                if not text:
                    print(f"{DIM}(no speech){RESET}")
                    continue
                print(f"{DIM}you (voice):{RESET} {text}")
            answer = await drive_turn(loop, text, conversation_id, conversations, config)
            if speak and answer:
                try:
                    async with Work("TTS") as w:  # dots while synth + playback run
                        w.chars = len(answer)
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
        await voice_io.play_cue()  # earcon: hotkey fired, mic is now listening
        print(f"{DIM}🎤 listening…{RESET}")
        try:
            text = await voice_io.record_and_transcribe(on_level=mic_meter)
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
        answer = await drive_turn(loop, text, conversation_id, conversations, config)
        if speak and answer:
            try:
                await voice_io.speak(answer)
            except Exception as exc:
                print(f"{DIM}(speech output failed: {exc}){RESET}")
    finally:
        scheduler.shutdown()
        store.close()
    return 0


async def drive_turn(loop, text, conversation_id, conversations, config) -> str:
    """Run one agent turn: stream events to the console, return the answer text."""
    parts: list[str] = []
    async for event in run_turn(
        loop, text, conversation_id, conversations, **summarize_kwargs(config)
    ):
        print_event(event)
        if isinstance(event, TokenEvent):
            parts.append(event.text)
    return "".join(parts).strip()
