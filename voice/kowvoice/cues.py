"""A short "mic is listening" earcon, played when a hands-free turn starts
(wake word or hotkey) so the user knows recording began. Best-effort: any failure
(no audio out, missing file) is swallowed — the cue must never break a turn."""

from __future__ import annotations

from pathlib import Path

DISABLED = {"off", "none", "0", "false", "no"}


def sound(name: str) -> Path | None:
    """Locate a bundled sound file: repo-root ./sounds/<name> (editable installs)
    or a package-local fallback. None if neither exists."""
    here = Path(__file__).resolve()
    for cand in (here.parents[2] / "sounds" / name, here.parent / "sounds" / name):
        if cand.exists():
            return cand
    return None


def default_cue() -> Path:
    """The shipped listening earcon; falls back to the repo-root path if absent."""
    return sound("listen.wav") or Path(__file__).resolve().parents[2] / "sounds" / "listen.wav"


def listen_cue_path(settings) -> Path | None:
    """Resolve the cue file: KOW_VOICE_LISTEN_SOUND overrides the default; an
    'off'/'none' value or a missing file yields None (no cue)."""
    raw = (getattr(settings, "listen_sound", "") or "").strip()
    if raw.lower() in DISABLED:
        return None
    path = Path(raw).expanduser() if raw else default_cue()
    return path if path.exists() else None


async def play_listen_cue(sink, settings) -> None:
    """Play the listening earcon on `sink` (the TTS output device). Never raises."""
    path = listen_cue_path(settings)
    if path is None:
        return
    try:
        from .types import AudioClip

        await sink.play(AudioClip(audio=path.read_bytes(), format="wav"))
    except Exception:
        pass
