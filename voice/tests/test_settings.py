from kowvoice.settings import VoiceSettings


def test_defaults(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no ./ttsgen.conf
    monkeypatch.delenv("STT_URL", raising=False)
    settings = VoiceSettings.load()
    assert settings.stt_url == "http://127.0.0.1:5099"
    assert settings.tts_url == "http://127.0.0.1:5000"
    assert settings.barge_in is True
    assert settings.sample_rate == 16000


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STT_URL", "http://10.0.0.5:5099")
    monkeypatch.setenv("STT_TOKEN", "tok")
    monkeypatch.setenv("KOW_BARGE_IN", "0")
    settings = VoiceSettings.load()
    assert settings.stt_url == "http://10.0.0.5:5099"
    assert settings.stt_token == "tok"
    assert settings.barge_in is False


def test_ttsgen_conf_chain(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TTS_URL", raising=False)
    (tmp_path / "ttsgen.conf").write_text('TTS_URL=http://tts.local:5000\nTTS_TOKEN="abc"\n')
    settings = VoiceSettings.load()
    assert settings.tts_url == "http://tts.local:5000"
    assert settings.tts_token == "abc"


def test_env_beats_conf_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ttsgen.conf").write_text("TTS_URL=http://from-file:5000\n")
    monkeypatch.setenv("TTS_URL", "http://from-env:5000")
    assert VoiceSettings.load().tts_url == "http://from-env:5000"
