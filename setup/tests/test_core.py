from pathlib import Path
from unittest.mock import patch

import pytest

from kow_setup.checks import CheckResult
from kow_setup.core import (
    build_voice_updates,
    normalize_ollama_url,
    normalize_url,
    parse_answers,
    run,
)


def answers_remote_ollama() -> dict:
    return {"ollama": {"mode": "remote", "url": "http://h:11434", "model": "qwen2.5:14b"}}


def test_parse_answers_defaults_to_skip():
    answers = parse_answers({})
    assert all(a.mode == "skip" for a in answers.values())


def test_parse_answers_invalid_mode():
    with pytest.raises(ValueError, match="invalid mode"):
        parse_answers({"stt": {"mode": "weird"}})


@patch("kow_setup.core.check_ollama")
def test_config_written_on_green(mock_check, tmp_path: Path):
    mock_check.return_value = CheckResult(service="ollama", ok=True, latency_ms=5)
    conf = tmp_path / "kowalski.conf"
    code, results = run(answers_remote_ollama(), conf)
    assert code == 0
    assert conf.exists()
    content = conf.read_text()
    assert "OLLAMA_HOST=http://h:11434" in content
    assert "OLLAMA_MODEL=qwen2.5:14b" in content


@patch("kow_setup.core.check_ollama")
def test_config_not_written_on_failure(mock_check, tmp_path: Path):
    mock_check.return_value = CheckResult(service="ollama", ok=False, error="unreachable")
    conf = tmp_path / "kowalski.conf"
    code, results = run(answers_remote_ollama(), conf)
    assert code == 1
    assert not conf.exists()


@patch("kow_setup.core.check_ollama")
def test_accept_warnings_overrides(mock_check, tmp_path: Path):
    mock_check.return_value = CheckResult(service="ollama", ok=False, error="unreachable")
    conf = tmp_path / "kowalski.conf"
    code, _ = run(answers_remote_ollama(), conf, accept_warnings=True)
    assert code == 0
    assert conf.exists()


def test_all_skip_writes_nothing(tmp_path: Path):
    conf = tmp_path / "kowalski.conf"
    code, results = run({}, conf)
    assert code == 0
    assert results == []
    assert not conf.exists()


def test_local_mode_not_implemented(tmp_path: Path):
    with pytest.raises(NotImplementedError):
        run({"ollama": {"mode": "local"}}, tmp_path / "c.conf")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("127.0.0.1", "http://127.0.0.1:11434"),         # bare host -> default port
        ("127.0.0.1:12345", "http://127.0.0.1:12345"),   # explicit port kept
        ("http://10.0.0.5", "http://10.0.0.5:11434"),    # scheme, no port
        ("http://10.0.0.5:11434", "http://10.0.0.5:11434"),
        ("https://ollama.local:443/", "https://ollama.local:443"),
        ("  10.16.69.251  ", "http://10.16.69.251:11434"),  # whitespace
    ],
)
def test_normalize_ollama_url(raw, expected):
    assert normalize_ollama_url(raw) == expected


def test_normalize_ollama_url_is_idempotent():
    once = normalize_ollama_url("10.16.69.251")
    assert normalize_ollama_url(once) == once


def test_parse_answers_normalizes_ollama_url():
    answers = parse_answers({"ollama": {"mode": "remote", "url": "127.0.0.1:12345"}})
    assert answers["ollama"].url == "http://127.0.0.1:12345"
    answers = parse_answers({"ollama": {"mode": "remote", "url": "10.0.0.5"}})
    assert answers["ollama"].url == "http://10.0.0.5:11434"


@pytest.mark.parametrize(
    "url, port, expected",
    [
        ("10.16.69.251:5051", 5099, "http://10.16.69.251:5051"),  # scheme added, port kept
        ("10.16.69.251", 5099, "http://10.16.69.251:5099"),       # stt default port
        ("10.16.69.251", 5000, "http://10.16.69.251:5000"),       # tts default port
        ("https://stt.local", 5099, "https://stt.local:5099"),
    ],
)
def test_normalize_url(url, port, expected):
    assert normalize_url(url, port) == expected


def test_parse_answers_normalizes_stt_tts_urls():
    answers = parse_answers(
        {
            "stt": {"mode": "remote", "url": "10.16.69.251:5051"},
            "tts": {"mode": "remote", "url": "10.16.69.251"},
        }
    )
    assert answers["stt"].url == "http://10.16.69.251:5051"  # scheme added (the reported bug)
    assert answers["tts"].url == "http://10.16.69.251:5000"  # default tts port


def test_build_voice_updates_maps_keys():
    updates = build_voice_updates(
        {"voice": {"wake_mode": "both", "wake_word": "hey_kowalski", "wake_model": "/m/k.onnx"}}
    )
    assert updates == {
        "KOW_WAKE_MODE": "both",
        "KOW_WAKE_WORD": "hey_kowalski",
        "KOW_WAKE_MODEL": "/m/k.onnx",
    }


def test_build_voice_updates_empty_when_absent():
    assert build_voice_updates({}) == {}


def test_build_voice_updates_invalid_mode():
    with pytest.raises(ValueError, match="invalid wake_mode"):
        build_voice_updates({"voice": {"wake_mode": "telepathy"}})


def test_voice_only_setup_writes_wake_config(tmp_path: Path):
    conf = tmp_path / "kowalski.conf"
    code, results = run({"voice": {"wake_mode": "both"}}, conf)
    assert code == 0
    assert results == []
    assert "KOW_WAKE_MODE=both" in conf.read_text()
