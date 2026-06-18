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

_MOD_NAMES = {"ctrl": "Ctrl", "control": "Ctrl", "alt": "Alt", "shift": "Shift",
              "super": "Super", "win": "Super", "meta": "Super", "cmd": "Cmd"}


def _fmt_hotkey(combo: str) -> str:
    """Pretty-print a 'mod+key' combo for the banner, e.g. 'alt+v' -> 'Alt+v'."""
    return "+".join(_MOD_NAMES.get(p.lower(), p) for p in combo.split("+"))


def _level_meter(rms: float, state: str) -> None:
    """Live mic level bar on the input line while recording (tty only)."""
    import sys

    if not sys.stdout.isatty():
        return
    filled = int(min(1.0, rms * 20) * 16)
    bar = "█" * filled + "·" * (16 - filled)
    label = {"waiting": "speak…", "speaking": "hearing you…", "ending": "…"}.get(state, "")
    sys.stdout.write(f"\r{DIM}🎤 [{bar}] {label}{RESET}\033[K")
    sys.stdout.flush()


class _Work:
    """A live progress line for a slow voice op (STT/TTS): cycles 1–3 dots
    ('TTS .' / '..' / '...') so the user sees something is happening, then rewrites
    the line as a summary 'TTS 123 chars (1.234s)'. The caller sets `.chars`; the
    elapsed time is measured around the `async with`. Animation is tty-only; the
    summary always prints (unless the body raised)."""

    def __init__(self, label: str, *, period: float = 0.35) -> None:
        self.label = label
        self.period = period
        self.chars = 0
        self._task = None
        self._t0 = 0.0

    async def __aenter__(self) -> "_Work":
        import sys
        import time

        self._t0 = time.monotonic()
        if sys.stdout.isatty():
            self._task = asyncio.ensure_future(self._spin())
        return self

    async def _spin(self) -> None:
        import sys

        i = 0
        try:
            while True:
                i = i % 3 + 1
                sys.stdout.write(f"\r{DIM}{self.label} {'.' * i}{RESET}\033[K")
                sys.stdout.flush()
                await asyncio.sleep(self.period)
        except asyncio.CancelledError:
            pass

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        import contextlib
        import sys
        import time

        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(BaseException):
                await self._task
        if exc_type is None:
            dt = time.monotonic() - self._t0
            tty = sys.stdout.isatty()
            head, tail = ("\r", "\033[K") if tty else ("", "")
            print(f"{head}{DIM}{self.label} {self.chars} chars ({dt:.3f}s){RESET}{tail}")
        return False


_TALK = object()  # sentinel: the raw reader returns this when the hotkey is pressed
_STOP = object()  # sentinel: the raw reader was cancelled (stop event set, e.g. wake fired)


def _hotkey_bytes(combo: str) -> bytes | None:
    """The bytes a terminal sends for an in-chat-usable hotkey, or None when the
    combo can't be one: a plain key collides with typing, and Shift/Super on
    printable keys aren't terminal-readable (use the global XFCE binding for those)."""
    if not combo:
        return None
    parts = [p.lower() for p in combo.split("+")]
    mods, key = parts[:-1], parts[-1]
    if not mods or any(m in ("shift", "super", "win", "meta", "cmd") for m in mods):
        return None
    if "ctrl" in mods or "control" in mods:
        if key == "space":
            seq = b"\x00"
        elif len(key) == 1 and key.isalpha():
            seq = bytes([ord(key) & 0x1F])
        else:
            return None
    elif len(key) == 1:
        seq = key.encode()
    else:
        return None
    return b"\x1b" + seq if "alt" in mods else seq


def _peek_byte(fd: int, timeout: float = 0.06) -> int | None:
    import os
    import select

    if select.select([fd], [], [], timeout)[0]:
        b = os.read(fd, 1)
        return b[0] if b else None
    return None


def _raw_read(prompt: str, hotkey: bytes | None, stop=None):
    """cbreak line reader: returns the typed line, _TALK on the hotkey; raises
    EOFError on Ctrl-D (empty) and KeyboardInterrupt on Ctrl-C. Basic editing
    only (printable + UTF-8 + Backspace); no history/arrows.

    When `stop` (a threading.Event) is given, the read polls instead of blocking
    so the worker can be cancelled (returns _STOP) — used to race typing against
    the wake word without orphaning a stuck os.read."""
    import os
    import select
    import sys
    import termios
    import tty

    fd = sys.stdin.fileno()
    sys.stdout.write(prompt)
    sys.stdout.flush()
    old = termios.tcgetattr(fd)
    buf: list[str] = []
    try:
        tty.setcbreak(fd)  # ICANON+ECHO off, ISIG on (Ctrl-C still raises)
        while True:
            if stop is not None:
                while not (stop.is_set() or select.select([fd], [], [], 0.1)[0]):
                    pass
                if stop.is_set():
                    return _STOP
            c = os.read(fd, 1)
            if not c:
                raise EOFError
            b = c[0]
            if b in (10, 13):  # Enter
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                return "".join(buf)
            if b == 4:  # Ctrl-D
                if not buf:
                    raise EOFError
                continue
            if b in (8, 127):  # Backspace
                if buf:
                    buf.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if b == 27:  # Esc: Alt-hotkey or an escape sequence
                nxt = _peek_byte(fd)
                if hotkey and hotkey[:1] == b"\x1b" and nxt is not None and nxt == hotkey[1]:
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    return _TALK
                if nxt == 0x5B:  # '[' -> consume the arrow/seq final byte
                    _peek_byte(fd)
                continue
            if hotkey and len(hotkey) == 1 and b == hotkey[0]:  # ctrl-* hotkey
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                return _TALK
            if 32 <= b < 127:  # printable ASCII
                buf.append(chr(b))
                sys.stdout.write(chr(b))
                sys.stdout.flush()
            elif b >= 0xC0:  # UTF-8 lead byte (e.g. Cyrillic) -> read the rest
                n = 2 if b < 0xE0 else 3 if b < 0xF0 else 4
                rest = b"".join(os.read(fd, 1) for _ in range(n - 1))
                try:
                    ch = (bytes([b]) + rest).decode("utf-8")
                    buf.append(ch)
                    sys.stdout.write(ch)
                    sys.stdout.flush()
                except Exception:
                    pass
            # other control bytes ignored (Ctrl-C arrives as SIGINT via ISIG)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _make_raw_reader(combo: str):
    return _reader_for(_hotkey_bytes(combo))


def _reader_for(hotkey: bytes | None):
    """A line reader bound to a precomputed hotkey (returns _TALK when pressed)."""
    return lambda prompt: _raw_read(prompt, hotkey)


def _build_chat_wake(settings):
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


async def _read_or_wake(loop_ev, reader, wake):
    """Race a cancellable raw read (reader(stop)) against wake.wait_for_wake().
    Returns the reader's result, or _TALK when the wake word fires first. Either
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
        return _TALK
    # typing won, or the wake listener errored. Surface an error (otherwise the
    # word silently stops working — e.g. the mic device failed to open) instead of
    # swallowing it; a clean cancellation is not an error.
    if wake_task.done() and not wake_task.cancelled() and wake_task.exception() is not None:
        import sys

        exc = wake_task.exception()
        if not getattr(wake, "_warned", False):  # once, so a broken mic isn't invisible
            wake._warned = True
            print(f"\r{DIM}wake word off — listener stopped: {type(exc).__name__}: {exc}{RESET}",
                  file=sys.stderr, flush=True)
    wake_task.cancel()  # drop the listener
    with contextlib.suppress(BaseException):
        await wake_task
    return await read_task  # awaits typing if wake errored first; re-raises EOF/etc.


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
        self._recorder = EnergyVadRecorder(
            settings.sample_rate, settings.vad_silence_ms, device=settings.input_device,
            onset_timeout=settings.no_speech_ms / 1000.0,
        )
        self._stt = HttpSttClient(settings.stt_url, settings.stt_token)
        self._tts = HttpTtsClient(settings.tts_url, settings.tts_token,
                                  language=settings.tts_language)
        self._sink = SoundDeviceSink(device=settings.output_device)

    async def record(self, on_level=None):
        """Capture one utterance from the mic (ends on trailing silence)."""
        return await self._recorder.record_utterance(on_level=on_level)

    async def transcribe(self, utterance) -> str | None:
        """Send a recorded utterance to STT; returns the text (or None if empty)."""
        if utterance is None or utterance.is_empty:
            return None
        transcript = await self._stt.transcribe(
            utterance, language=self.settings.stt_language or None
        )
        return (transcript.text or "").strip() or None

    async def record_and_transcribe(self, on_level=None) -> str | None:
        return await self.transcribe(await self.record(on_level=on_level))

    async def play_cue(self) -> None:
        """Play the 'listening' earcon on the output device (best-effort)."""
        from .cues import play_listen_cue

        await play_listen_cue(self._sink, self.settings)

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
        raw_hotkey = _hotkey_bytes(config.get("KOW_VOICE_HOTKEY", ""))
        if wake is None:
            wake = _build_chat_wake(vsettings)
        if raw_hotkey is not None or wake is not None:
            input_fn = _reader_for(raw_hotkey)
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
            triggers.append(_fmt_hotkey(hk))
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
                    line = await _read_or_wake(
                        asyncio.get_event_loop(),
                        lambda stop: _raw_read(prompt, raw_hotkey, stop=stop),
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
            by_voice = line is _TALK  # hands-free trigger (hotkey / wake word)
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
                    await voice_io.play_cue()  # earcon: mic is now listening
                # Inline indicator on the input line; \r + clear-to-EOL (\033[K)
                # overwrites it in place with the result (or the cancel/error).
                print(f"{DIM}🎤 listening… (speak; silence ends it){RESET}", end="", flush=True)
                try:
                    utterance = await voice_io.record(on_level=_level_meter)
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
                    async with _Work("STT") as w:  # dots while the network STT runs
                        text = await voice_io.transcribe(utterance)
                        w.chars = len(text or "")
                except Exception as exc:
                    print(f"\r{DIM}(transcription failed: {exc}){RESET}\033[K")
                    continue
                if not text:
                    print(f"{DIM}(no speech){RESET}")
                    continue
                print(f"{DIM}you (voice):{RESET} {text}")
            answer = await _drive_turn(loop, text, conversation_id, conversations, config)
            if speak and answer:
                try:
                    async with _Work("TTS") as w:  # dots while synth + playback run
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
            text = await voice_io.record_and_transcribe(on_level=_level_meter)
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
