"""A short "mic is listening" earcon, played when a hands-free turn starts
(wake word or hotkey) so the user knows recording began. Best-effort: any failure
(no audio out, missing file) is swallowed — the cue must never break a turn."""

from __future__ import annotations

from pathlib import Path

DISABLED = {"off", "none", "0", "false", "no"}


def default_cue() -> Path:
    """The shipped earcon: repo-root ./sounds/listen.wav (editable installs), with
    a package-local fallback. Returns the first that exists, else the repo-root path."""
    here = Path(__file__).resolve()
    candidates = (
        here.parents[2] / "sounds" / "listen.wav",  # <repo>/sounds (editable install)
        here.parent / "sounds" / "listen.wav",       # packaged fallback
    )
    return next((c for c in candidates if c.exists()), candidates[0])


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
