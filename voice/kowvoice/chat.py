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


_TALK = object()  # sentinel: the raw reader returns this when the hotkey is pressed


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


def _raw_read(prompt: str, hotkey: bytes | None):
    """cbreak line reader: returns the typed line, _TALK on the hotkey; raises
    EOFError on Ctrl-D (empty) and KeyboardInterrupt on Ctrl-C. Basic editing
    only (printable + UTF-8 + Backspace); no history/arrows."""
    import os
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
    hotkey = _hotkey_bytes(combo)
    return lambda prompt: _raw_read(prompt, hotkey)


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
            settings.sample_rate, settings.vad_silence_ms, device=settings.input_device
        )
        self._stt = HttpSttClient(settings.stt_url, settings.stt_token)
        self._tts = HttpTtsClient(settings.tts_url, settings.tts_token,
                                  language=settings.tts_language)
        self._sink = SoundDeviceSink(device=settings.output_device)

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
    input_fn=None,
    voice_io=None,
) -> int:
    """Run the unified chat loop. `speak` toggles voice I/O; `input_fn`/`voice_io`
    are injectable for tests. With no input_fn, a tty + a usable KOW_VOICE_HOTKEY
    switches to a raw-mode reader so the hotkey can start a turn in the input line."""
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
        hotkey = config.get("KOW_VOICE_HOTKEY", "").strip()
        extra = f" (or {_fmt_hotkey(hotkey)})" if hotkey else ""
        print(
            f"{DIM}Type a message, or press Enter on an empty line{extra} to talk. "
            f"'quit' or Ctrl-D to exit.{RESET}"
        )
    else:
        print(f"{DIM}Type a message. 'quit' or Ctrl-D to exit.{RESET}")

    if input_fn is None:
        import sys

        hotkey = config.get("KOW_VOICE_HOTKEY", "")
        if speak and sys.stdin.isatty() and _hotkey_bytes(hotkey) is not None:
            input_fn = _make_raw_reader(hotkey)  # raw mode: the hotkey starts a turn
        else:
            input_fn = input  # cooked input() keeps readline history/editing

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
            if line is _TALK:  # raw-mode hotkey -> start a turn now
                text = ""
            else:
                text = (line or "").strip()
                if text in ("exit", "quit", ":q"):
                    break
            if not text:
                if not speak:
                    continue
                # Inline indicator on the input line; \r + clear-to-EOL (\033[K)
                # overwrites it in place with the result (or the cancel/error).
                print(f"{DIM}🎤 listening… (speak; silence ends it){RESET}", end="", flush=True)
                try:
                    text = await voice_io.record_and_transcribe()
                except (KeyboardInterrupt, asyncio.CancelledError):
                    # Ctrl-C while recording cancels just this turn (the mic stream
                    # tears down) — back to the prompt instead of crashing out.
                    print(f"\r{DIM}(cancelled){RESET}\033[K")
                    continue
                except Exception as exc:
                    print(f"\r{DIM}(voice input failed: {exc}){RESET}\033[K")
                    continue
                if not text:
                    print(f"\r{DIM}(no speech){RESET}\033[K")
                    continue
                print(f"\r{DIM}you (voice):{RESET} {text}\033[K")
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
        print(f"{DIM}🎤 listening…{RESET}")
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
