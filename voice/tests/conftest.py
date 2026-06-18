import pytest

from kowvoice.settings import VoiceSettings


@pytest.fixture
def settings(tmp_path):
    return VoiceSettings(
        stt_url="http://127.0.0.1:5099",
        stt_token="",
        stt_language="",
        tts_url="http://127.0.0.1:5000",
        tts_token="",
        tts_engine="",
        wake_mode="push_to_talk",
        wake_word="hey_kowalski",
        wake_model="",
        wake_threshold=0.5,
        sample_rate=16000,
        vad_silence_ms=700,
        barge_in=True,
        socket_path=tmp_path / "kowalski.sock",
        listen_sound="off",  # no earcon in the headless orchestrator tests
    )


@pytest.fixture
def events():
    captured = []
    return captured, captured.append
