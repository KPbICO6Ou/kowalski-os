"""`kow-voice test`: a round-trip self-test of the voice stack.

Flow: greet via TTS → record a phrase → transcribe (STT) → echo it back via TTS
→ done. On any failure it probes connectivity and asks the LLM to diagnose the
problem (given the error, the voice settings, and the check results).

Everything network/hardware sits behind injectable seams so the flow is testable
with the mocks in `mocks.py` (no microphone, services, or Ollama needed)."""

from __future__ import annotations

DIM = "\033[2m"
RESET = "\033[0m"
CYAN = "\033[36m"   # TTS lines
GREEN = "\033[32m"  # STT lines


def _device_label(configured: str, which: int) -> str:
    """Human name of the device in use: the configured one, else the system
    default (which=0 input, 1 output). Best-effort; never raises."""
    if configured:
        return configured
    try:
        import sounddevice as sd

        idx = sd.default.device[which]
        if isinstance(idx, int) and idx >= 0:
            return sd.query_devices(idx)["name"]
    except Exception:
        pass
    return "system default"


PHRASES = {
    "en": {
        "greet": "Hello. Please say something after the tone.",
        "echo": "You said: {text}",
        "nospeech": "I did not catch anything.",
        "done": "Test complete.",
    },
    "ru": {
        "greet": "Привет. Скажите что-нибудь после сигнала.",
        "echo": "Вы сказали: {text}",
        "nospeech": "Я ничего не расслышал.",
        "done": "Конец теста.",
    },
}


def _phrases(language: str) -> dict[str, str]:
    return PHRASES.get((language or "en").split("-")[0].lower(), PHRASES["en"])


def _real_components(settings):
    from .audio_devices import EnergyVadRecorder, SoundDeviceSink
    from .stt_http import HttpSttClient
    from .tts_http import HttpTtsClient

    silence_ms = max(settings.vad_silence_ms, 1000)  # ~1 s of silence confirms you finished
    return (
        EnergyVadRecorder(settings.sample_rate, silence_ms, device=settings.input_device),
        HttpSttClient(settings.stt_url, settings.stt_token),
        HttpTtsClient(settings.tts_url, settings.tts_token, language=settings.tts_language),
        SoundDeviceSink(device=settings.output_device),
    )


async def _probe(settings) -> list[str]:
    """STT / TTS / kow-core connectivity, one line each."""
    import asyncio

    from .stt_http import HttpSttClient
    from .tts_http import HttpTtsClient

    lines: list[str] = []
    for name, client in (
        ("STT", HttpSttClient(settings.stt_url, settings.stt_token, timeout=5.0)),
        ("TTS", HttpTtsClient(settings.tts_url, settings.tts_token, timeout=5.0)),
    ):
        try:
            health = await client.health()
            lines.append(f"[OK]   {name} {client.url} — {health}")
        except Exception as exc:
            lines.append(f"[FAIL] {name} {client.url} — {exc}")
    try:
        reader, writer = await asyncio.open_unix_connection(str(settings.socket_path))
        writer.write(b'{"op": "status"}\n')
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=5)
        writer.close()
        lines.append(f"[OK]   core {settings.socket_path} — {line.decode().strip()}")
    except Exception as exc:
        lines.append(f"[FAIL] core {settings.socket_path} — {exc}")
    return lines


async def _llm_diagnose(llm, prompt: str) -> str:
    parts: list[str] = []
    async for chunk in llm.chat([{"role": "user", "content": prompt}], []):
        parts.append(chunk.content_delta)
    return "".join(parts).strip()


def _diag_prompt(settings, problem: str, checks: list[str]) -> str:
    return (
        "You are diagnosing a voice-assistant self-test failure on Kowalski OS "
        "(local STT/TTS HTTP services + an Ollama-backed agent over a unix socket).\n"
        f"Problem: {problem}\n"
        f"Settings: STT_URL={settings.stt_url} TTS_URL={settings.tts_url} "
        f"TTS_ENGINE={settings.tts_engine or 'default'} STT_LANGUAGE={settings.stt_language or 'default'} "
        f"wake_mode={settings.wake_mode}\n"
        "Connectivity checks:\n" + "\n".join(checks) + "\n\n"
        "Give the single most likely cause and concrete fix steps (service to start, "
        "port, microphone/audio device, or config key). Be brief and specific.\n"
        f"Write the whole answer in the user's language (language code: "
        f"{settings.stt_language or 'en'})."
    )


async def _diagnose(settings, problem, llm, probe_fn, on_text) -> int:
    on_text(f"\n⚠ {problem}")
    checks = await probe_fn(settings)
    on_text("diagnostics:")
    for line in checks:
        on_text("  " + line)
    try:
        if llm is None:
            from kowalski.bootstrap import build_llm
            from kowalski.config import Config

            llm = build_llm(Config.load())
        on_text(f"{DIM}asking the LLM to diagnose…{RESET}")
        answer = await _llm_diagnose(llm, _diag_prompt(settings, problem, checks))
        on_text("\nLLM diagnosis:\n" + answer)
    except Exception as exc:
        on_text(f"(LLM diagnosis unavailable: {exc})")
    return 1


async def run_test(
    *,
    settings=None,
    recorder=None,
    stt=None,
    tts=None,
    sink=None,
    llm=None,
    probe_fn=_probe,
    on_text=print,
) -> int:
    """Run the round-trip self-test. Returns 0 on success, 1 on a diagnosed
    failure. All collaborators are injectable for tests."""
    if settings is None:
        from .settings import VoiceSettings

        settings = VoiceSettings.load()
    phrases = _phrases(settings.stt_language)

    real_used = None in (recorder, stt, tts, sink)
    if real_used:
        try:
            real = _real_components(settings)
        except Exception as exc:
            return await _diagnose(settings, f"could not initialise the voice stack: {exc}",
                                   llm, probe_fn, on_text)
        recorder = recorder or real[0]
        stt = stt or real[1]
        tts = tts or real[2]
        sink = sink or real[3]

    mic = _device_label(settings.input_device, 0) if real_used else (settings.input_device or "mock")
    spk = _device_label(settings.output_device, 1) if real_used else (settings.output_device or "mock")

    import sys
    import time

    def on_level(rms: float, state: str) -> None:
        if not sys.stdout.isatty():
            return
        filled = int(min(1.0, rms * 20) * 18)
        bar = "█" * filled + "·" * (18 - filled)
        label = {"waiting": "speak now", "speaking": "hearing you…",
                 "ending": "finishing…"}.get(state, "")
        sys.stdout.write(f"\r{DIM}SYS › mic [{bar}] {label}{RESET}   ")
        sys.stdout.flush()

    async def say(text: str) -> None:
        on_text(f"{CYAN}TTS{RESET} › {text}")
        t0 = time.monotonic()
        clip = await tts.synthesize(text)
        on_text(f"{DIM}SYS ·   synthesized in {time.monotonic() - t0:.1f}s — speaking…{RESET}")
        await sink.play(clip)

    try:
        on_text(f"{DIM}SYS › mic: {mic}  ·  speaker: {spk}{RESET}")
        on_text(f"{DIM}SYS › say a short phrase after the greeting — it gets echoed back{RESET}")
        await say(phrases["greet"])
        on_text(f"{DIM}SYS › listening… speak now (mic: {mic}){RESET}")
        utterance = await recorder.record_utterance(on_level=on_level)
        if sys.stdout.isatty():
            sys.stdout.write("\r" + " " * 60 + "\r")  # clear the live meter line
            sys.stdout.flush()
        if utterance is None or utterance.is_empty:
            await say(phrases["nospeech"])
            return await _diagnose(settings, "no speech captured from the microphone",
                                   llm, probe_fn, on_text)
        on_text(f"{DIM}SYS › recorded — transcribing…{RESET}")
        t0 = time.monotonic()
        transcript = await stt.transcribe(utterance, language=settings.stt_language or None)
        stt_s = time.monotonic() - t0
        text = (transcript.text or "").strip()
        if not text:
            await say(phrases["nospeech"])
            return await _diagnose(settings, "STT returned an empty transcript",
                                   llm, probe_fn, on_text)
        on_text(f"{GREEN}STT{RESET} › {text}  {DIM}({stt_s:.1f}s){RESET}")
        await say(phrases["echo"].format(text=text))
        await say(phrases["done"])
        on_text(f"{DIM}SYS ✓ voice round-trip OK{RESET}")
        return 0
    except Exception as exc:
        return await _diagnose(settings, f"voice round-trip failed: {exc}",
                               llm, probe_fn, on_text)
