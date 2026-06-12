from pathlib import Path
from unittest.mock import patch

import pytest

from kow_setup.checks import CheckResult
from kow_setup.core import parse_answers, run


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
