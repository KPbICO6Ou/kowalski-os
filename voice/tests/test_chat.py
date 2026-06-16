"""Unified voice + text chat loop (kowvoice.chat.run_chat).

The agent is stubbed by monkeypatching run_turn; voice I/O and stdin are injected
so the loop runs with no Ollama, microphone, or TTS service."""

import pytest

from kowalski.agent.events import TokenEvent
from kowvoice import chat


def _scripted_input(lines):
    it = iter(lines)

    def fake(prompt=""):
        try:
            return next(it)
        except StopIteration as exc:
            raise EOFError from exc

    return fake


class FakeVoiceIO:
    def __init__(self, transcripts=None):
        self._transcripts = list(transcripts or [])
        self.spoken = []

    async def record_and_transcribe(self):
        return self._transcripts.pop(0) if self._transcripts else None

    async def speak(self, text):
        self.spoken.append(text)


def _fake_run_turn(answers):
    answers = list(answers)
    calls = []

    async def run_turn(loop, text, conversation_id, conversations, **kwargs):
        calls.append(text)
        yield TokenEvent(text=answers.pop(0) if answers else "ok")

    run_turn.calls = calls
    return run_turn


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("KOW_DB_PATH", str(tmp_path / "chat.db"))
    monkeypatch.setenv("KOW_ALLOWED_PATHS", str(tmp_path))
    monkeypatch.setenv("KOW_MEMORY", "0")
    monkeypatch.setenv("KOW_SUMMARIZE", "0")


async def test_text_turn_prints_and_speaks(monkeypatch, capsys):
    rt = _fake_run_turn(["Hello there."])
    monkeypatch.setattr(chat, "run_turn", rt)
    vio = FakeVoiceIO()
    rc = await chat.run_chat(speak=True, voice_io=vio, input_fn=_scripted_input(["hi", "quit"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Hello there." in out
    assert rt.calls == ["hi"]
    assert vio.spoken == ["Hello there."]  # answer was both printed and spoken


async def test_empty_line_triggers_voice_then_speaks(monkeypatch, capsys):
    rt = _fake_run_turn(["Answer to voice."])
    monkeypatch.setattr(chat, "run_turn", rt)
    vio = FakeVoiceIO(["what time is it"])
    rc = await chat.run_chat(speak=True, voice_io=vio, input_fn=_scripted_input(["", "quit"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "you (voice):" in out and "what time is it" in out
    assert rt.calls == ["what time is it"]
    assert vio.spoken == ["Answer to voice."]


async def test_empty_voice_no_speech_runs_no_turn(monkeypatch, capsys):
    rt = _fake_run_turn(["unused"])
    monkeypatch.setattr(chat, "run_turn", rt)
    vio = FakeVoiceIO([None])  # mic produced no speech
    assert await chat.run_chat(speak=True, voice_io=vio, input_fn=_scripted_input(["", "quit"])) == 0
    assert "(no speech)" in capsys.readouterr().out
    assert rt.calls == []  # no agent turn ran


async def test_text_only_mode_ignores_empty_and_does_not_speak(monkeypatch):
    rt = _fake_run_turn(["T."])
    monkeypatch.setattr(chat, "run_turn", rt)
    vio = FakeVoiceIO(["should not be used"])
    await chat.run_chat(speak=False, voice_io=vio, input_fn=_scripted_input(["", "hi", "quit"]))
    assert rt.calls == ["hi"]  # the empty line was ignored, not push-to-talk
    assert vio.spoken == []  # text-only: nothing spoken


async def test_multi_turn_shares_one_conversation(monkeypatch, capsys):
    rt = _fake_run_turn(["First.", "Second."])
    monkeypatch.setattr(chat, "run_turn", rt)
    vio = FakeVoiceIO(["second question"])
    rc = await chat.run_chat(
        speak=True, voice_io=vio, input_fn=_scripted_input(["first question", "", "quit"])
    )
    assert rc == 0
    assert rt.calls == ["first question", "second question"]
    assert vio.spoken == ["First.", "Second."]
