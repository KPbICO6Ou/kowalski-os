import pytest

from kowvoice.settings import VoiceSettings


@pytest.fixture(autouse=True)
def isolate_conf(monkeypatch, tmp_path):
    """Keep tests off the real ~/.config files: no ttsgen.conf in cwd, and the
    kow-core config points at a (by default absent) temp file."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KOW_CONFIG", str(tmp_path / "kowalski.conf"))
    for key in ("STT_URL", "TTS_URL", "STT_TOKEN", "KOW_BARGE_IN", "KOW_WAKE_MODE"):
        monkeypatch.delenv(key, raising=False)


def test_defaults():
    settings = VoiceSettings.load()
    assert settings.stt_url == "http://127.0.0.1:5099"
    assert settings.tts_url == "http://127.0.0.1:5000"
    assert settings.barge_in is True
    assert settings.sample_rate == 16000
    assert settings.wake_mode == "push_to_talk"
    assert settings.wake_word == "hey_kowalski"
    assert settings.wake_threshold == 0.5


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("STT_URL", "http://10.0.0.5:5099")
    monkeypatch.setenv("STT_TOKEN", "tok")
    monkeypatch.setenv("KOW_BARGE_IN", "0")
    settings = VoiceSettings.load()
    assert settings.stt_url == "http://10.0.0.5:5099"
    assert settings.stt_token == "tok"
    assert settings.barge_in is False


def test_ttsgen_conf_chain(monkeypatch, tmp_path):
    monkeypatch.delenv("TTS_URL", raising=False)
    (tmp_path / "ttsgen.conf").write_text('TTS_URL=http://tts.local:5000\nTTS_TOKEN="abc"\n')
    settings = VoiceSettings.load()
    assert settings.tts_url == "http://tts.local:5000"
    assert settings.tts_token == "abc"


def test_env_beats_conf_file(monkeypatch, tmp_path):
    (tmp_path / "ttsgen.conf").write_text("TTS_URL=http://from-file:5000\n")
    monkeypatch.setenv("TTS_URL", "http://from-env:5000")
    assert VoiceSettings.load().tts_url == "http://from-env:5000"


def test_reads_kowalski_conf_written_by_setup(monkeypatch, tmp_path):
    # What `kow-setup` writes (kowalski.conf) must reach kow-voice.
    (tmp_path / "kowalski.conf").write_text(
        "STT_URL=http://10.16.69.251:5099\n"
        "TTS_URL=http://10.16.69.251:5000\n"
        "KOW_WAKE_MODE=both\n"
        "KOW_WAKE_WORD=hey_kowalski\n"
    )
    settings = VoiceSettings.load()
    assert settings.stt_url == "http://10.16.69.251:5099"
    assert settings.tts_url == "http://10.16.69.251:5000"
    assert settings.wake_mode == "both"


def test_ttsgen_conf_overrides_kowalski_conf(monkeypatch, tmp_path):
    (tmp_path / "kowalski.conf").write_text("TTS_URL=http://from-core:5000\n")
    (tmp_path / "ttsgen.conf").write_text("TTS_URL=http://from-ttsgen:5000\n")
    assert VoiceSettings.load().tts_url == "http://from-ttsgen:5000"
