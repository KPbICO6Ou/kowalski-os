"""Wake-listener selection and the push-to-talk-OR-wake-word race.

The real openWakeWord detection needs a microphone and a model, so it isn't run
here; the factory and the CombinedWake control flow are exercised with fakes."""

import asyncio

import pytest

from kowvoice.audio_devices import (
    CombinedWake,
    OpenWakeWordListener,
    PushToTalkWake,
    build_wake,
)
from kowvoice.settings import VoiceSettings


def _settings(**over) -> VoiceSettings:
    base = dict(
        stt_url="",
        stt_token="",
        stt_language="",
        tts_url="",
        tts_token="",
        tts_engine="",
        wake_mode="push_to_talk",
        wake_word="hey_kowalski",
        wake_model="",
        wake_threshold=0.5,
        sample_rate=16000,
        vad_silence_ms=700,
        barge_in=True,
        socket_path="/tmp/x.sock",
    )
    base.update(over)
    return VoiceSettings(**base)


def test_build_wake_push_to_talk():
    assert isinstance(build_wake(_settings(wake_mode="push_to_talk")), PushToTalkWake)


def test_build_wake_wake_word():
    wake = build_wake(_settings(wake_mode="wake_word", wake_model="/models/kowalski.onnx"))
    assert isinstance(wake, OpenWakeWordListener)
    assert wake.model == "/models/kowalski.onnx"
    assert wake.threshold == 0.5


def test_build_wake_word_falls_back_to_wake_word_name():
    wake = build_wake(_settings(wake_mode="wake_word", wake_model="", wake_word="hey_jarvis"))
    assert isinstance(wake, OpenWakeWordListener)
    assert wake.model == "hey_jarvis"


def test_build_wake_both():
    wake = build_wake(_settings(wake_mode="both"))
    assert isinstance(wake, CombinedWake)
    kinds = {type(listener) for listener in wake.listeners}
    assert PushToTalkWake in kinds
    assert OpenWakeWordListener in kinds


def test_build_wake_unknown_mode_is_safe():
    assert isinstance(build_wake(_settings(wake_mode="nonsense")), PushToTalkWake)


class _FakeWake:
    def __init__(self, *, fires_after=None, raises=None):
        self._fires_after = fires_after
        self._raises = raises
        self.cancelled = False

    async def wait_for_wake(self):
        try:
            if self._raises is not None:
                raise self._raises
            if self._fires_after is not None:
                await asyncio.sleep(self._fires_after)
                return
            await asyncio.Event().wait()  # block forever
        except asyncio.CancelledError:
            self.cancelled = True
            raise


async def test_combined_returns_when_first_fires():
    fast = _FakeWake(fires_after=0.01)
    slow = _FakeWake()  # never fires
    await asyncio.wait_for(CombinedWake([fast, slow]).wait_for_wake(), timeout=1)
    assert slow.cancelled  # the loser is cancelled


async def test_combined_survives_a_listener_that_errors():
    broken = _FakeWake(raises=RuntimeError("no model"))
    good = _FakeWake(fires_after=0.01)
    # broken errors immediately; good should still drive the wake.
    await asyncio.wait_for(CombinedWake([broken, good]).wait_for_wake(), timeout=1)


async def test_combined_raises_when_all_listeners_error():
    a = _FakeWake(raises=RuntimeError("a"))
    b = _FakeWake(raises=RuntimeError("b"))
    with pytest.raises(RuntimeError):
        await CombinedWake([a, b]).wait_for_wake()
