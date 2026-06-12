from pathlib import Path

from kow_setup.config import read_conf, write_conf


def test_roundtrip(tmp_path: Path):
    conf = tmp_path / "kowalski.conf"
    write_conf(conf, {"OLLAMA_HOST": "http://x:11434", "STT_URL": "http://y:5099"})
    values = read_conf(conf)
    assert values["OLLAMA_HOST"] == "http://x:11434"
    assert values["STT_URL"] == "http://y:5099"


def test_unknown_keys_preserved(tmp_path: Path):
    conf = tmp_path / "kowalski.conf"
    conf.write_text("CUSTOM_KEY=keep-me\nOLLAMA_HOST=old\n")
    write_conf(conf, {"OLLAMA_HOST": "new"})
    values = read_conf(conf)
    assert values["CUSTOM_KEY"] == "keep-me"
    assert values["OLLAMA_HOST"] == "new"


def test_creates_parent_dirs_and_mode(tmp_path: Path):
    conf = tmp_path / "deep" / "nested" / "kowalski.conf"
    write_conf(conf, {"K": "v"})
    assert conf.exists()
    assert (conf.stat().st_mode & 0o777) == 0o600


def test_read_missing_returns_empty(tmp_path: Path):
    assert read_conf(tmp_path / "nope.conf") == {}
