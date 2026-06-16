"""kow-voice test (round-trip self-test + LLM-assisted diagnosis)."""

from kowalski.agent.llm import ChatChunk
from kowvoice import selftest
from kowvoice.mocks import MockAudioSink, MockRecorder, MockSttClient, MockTtsClient, silent_utterance
from kowvoice.settings import VoiceSettings


def _settings(language="en"):
    return VoiceSettings(
        stt_url="http://stt", stt_token="", stt_language=language,
        tts_url="http://tts", tts_token="", tts_engine="",
        wake_mode="push_to_talk", wake_word="hey_kowalski", wake_model="", wake_threshold=0.5,
        sample_rate=16000, vad_silence_ms=700, barge_in=True, socket_path="/tmp/x.sock",
    )


class FakeLLM:
    def __init__(self, text="Likely the TTS service is down; start it on the TTS_URL port."):
        self.text = text
        self.calls = []

    async def chat(self, messages, tools):
        self.calls.append(messages)
        yield ChatChunk(content_delta=self.text, done=True)


async def _noprobe(settings):
    return ["[OK]   STT http://stt — ok", "[FAIL] TTS http://tts — refused"]


def _collect():
    lines = []
    return lines, lines.append


async def test_happy_round_trip_speaks_greet_echo_done():
    lines, on_text = _collect()
    tts = MockTtsClient()
    rc = await selftest.run_test(
        settings=_settings(),
        recorder=MockRecorder([silent_utterance()]),
        stt=MockSttClient(["turn on the lights"]),
        tts=tts,
        sink=MockAudioSink(),
        llm=FakeLLM(),
        probe_fn=_noprobe,
        on_text=on_text,
    )
    assert rc == 0
    out = "\n".join(lines)
    assert "Hello. Please say something" in out  # greeting spoken
    assert "heard: “turn on the lights”" in out
    assert "You said: turn on the lights" in out  # echo spoken
    assert "Test complete." in out
    # greet, echo, done were all synthesized
    assert any("Hello" in c for c in tts.calls)
    assert any("You said: turn on the lights" == c for c in tts.calls)


async def test_russian_phrases_selected_by_language():
    lines, on_text = _collect()
    rc = await selftest.run_test(
        settings=_settings(language="ru"),
        recorder=MockRecorder([silent_utterance()]),
        stt=MockSttClient(["привет"]),
        tts=MockTtsClient(),
        sink=MockAudioSink(),
        llm=FakeLLM(),
        probe_fn=_noprobe,
        on_text=on_text,
    )
    assert rc == 0
    out = "\n".join(lines)
    assert "Скажите что-нибудь" in out
    assert "Вы сказали: привет" in out


async def test_no_speech_triggers_llm_diagnosis():
    lines, on_text = _collect()
    llm = FakeLLM("Check the microphone is the default input device.")
    rc = await selftest.run_test(
        settings=_settings(),
        recorder=MockRecorder([]),  # no utterance -> None
        stt=MockSttClient([]),
        tts=MockTtsClient(),
        sink=MockAudioSink(),
        llm=llm,
        probe_fn=_noprobe,
        on_text=on_text,
    )
    assert rc == 1
    out = "\n".join(lines)
    assert "no speech captured" in out
    assert "LLM diagnosis:" in out
    assert "default input device" in out
    assert llm.calls  # the LLM was consulted


async def test_empty_transcript_triggers_diagnosis():
    lines, on_text = _collect()
    rc = await selftest.run_test(
        settings=_settings(),
        recorder=MockRecorder([silent_utterance()]),
        stt=MockSttClient([""]),  # empty transcript
        tts=MockTtsClient(),
        sink=MockAudioSink(),
        llm=FakeLLM(),
        probe_fn=_noprobe,
        on_text=on_text,
    )
    assert rc == 1
    assert "STT returned an empty transcript" in "\n".join(lines)


async def test_tts_failure_is_diagnosed():
    lines, on_text = _collect()

    class BoomTts:
        async def synthesize(self, text):
            raise RuntimeError("connection refused")

    llm = FakeLLM("Start the TTS service.")
    rc = await selftest.run_test(
        settings=_settings(),
        recorder=MockRecorder([silent_utterance()]),
        stt=MockSttClient(["hi"]),
        tts=BoomTts(),
        sink=MockAudioSink(),
        llm=llm,
        probe_fn=_noprobe,
        on_text=on_text,
    )
    assert rc == 1
    out = "\n".join(lines)
    assert "voice round-trip failed" in out and "connection refused" in out
    assert "LLM diagnosis:" in out


async def test_diagnosis_survives_unavailable_llm():
    lines, on_text = _collect()

    class DeadLLM:
        async def chat(self, messages, tools):
            raise RuntimeError("ollama down")
            yield  # pragma: no cover

    rc = await selftest.run_test(
        settings=_settings(),
        recorder=MockRecorder([]),
        stt=MockSttClient([]),
        tts=MockTtsClient(),
        sink=MockAudioSink(),
        llm=DeadLLM(),
        probe_fn=_noprobe,
        on_text=on_text,
    )
    assert rc == 1
    assert "LLM diagnosis unavailable" in "\n".join(lines)
