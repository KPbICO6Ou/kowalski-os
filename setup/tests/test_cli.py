"""Interactive prompts: the Ollama probe + model picker."""

import builtins
from unittest.mock import patch

from kow_setup import cli
from kow_setup.checks import CheckResult


def _inputs(seq):
    it = iter(seq)
    return lambda prompt="": next(it)


def test_default_mode_from_current_config():
    assert cli._default_mode("ollama", {"OLLAMA_HOST": "http://h:11434"}) == "r"
    assert cli._default_mode("stt", {}) == "s"
    assert cli._default_mode("tts", {"TTS_URL": "http://h:5000"}) == "r"


def test_choose_model_by_number(monkeypatch):
    monkeypatch.setattr(builtins, "input", _inputs(["2"]))
    assert cli._choose_model(["a", "b", "c"]) == "b"


def test_choose_model_blank_keeps_current(monkeypatch):
    monkeypatch.setattr(builtins, "input", _inputs([""]))
    assert cli._choose_model(["a", "qwen3:8b"], current="qwen3:8b") == "qwen3:8b"


def test_choose_model_blank_is_server_default(monkeypatch):
    monkeypatch.setattr(builtins, "input", _inputs([""]))
    assert cli._choose_model(["a", "b"]) == ""


def test_choose_model_by_name(monkeypatch):
    monkeypatch.setattr(builtins, "input", _inputs(["qwen3:8b"]))
    assert cli._choose_model(["a", "b"]) == "qwen3:8b"


def test_choose_model_out_of_range_used_literally(monkeypatch):
    monkeypatch.setattr(builtins, "input", _inputs(["9"]))
    assert cli._choose_model(["a", "b"]) == "9"


def test_choose_model_no_models_falls_back_to_typing(monkeypatch):
    monkeypatch.setattr(builtins, "input", _inputs(["typed:model"]))
    assert cli._choose_model([]) == "typed:model"


@patch("kow_setup.checks.check_ollama")
def test_ask_ollama_probes_normalizes_and_lists(mock_check, monkeypatch):
    mock_check.return_value = CheckResult(
        service="ollama", ok=True, latency_ms=3, detail={"models": ["qwen3:8b", "qwen3:30b"]}
    )
    monkeypatch.setattr(builtins, "input", _inputs(["10.16.69.251", "1"]))
    entry = cli.ask_ollama()
    assert entry == {"mode": "remote", "url": "http://10.16.69.251:11434", "model": "qwen3:8b"}
    mock_check.assert_called_once_with("http://10.16.69.251:11434")


@patch("kow_setup.checks.check_ollama")
def test_ask_ollama_keeps_explicit_port(mock_check, monkeypatch):
    mock_check.return_value = CheckResult(
        service="ollama", ok=True, latency_ms=1, detail={"models": ["m"]}
    )
    monkeypatch.setattr(builtins, "input", _inputs(["127.0.0.1:12345", ""]))
    entry = cli.ask_ollama()
    assert entry["url"] == "http://127.0.0.1:12345"
    assert "model" not in entry  # blank -> server default


@patch("kow_setup.checks.check_ollama")
def test_ask_ollama_retries_then_succeeds(mock_check, monkeypatch):
    mock_check.side_effect = [
        CheckResult(service="ollama", ok=False, error="refused"),
        CheckResult(service="ollama", ok=True, latency_ms=2, detail={"models": ["qwen3:8b"]}),
    ]
    # bad URL, accept re-entry (blank=Y), good URL, pick #1
    monkeypatch.setattr(builtins, "input", _inputs(["badhost", "", "10.0.0.9", "1"]))
    entry = cli.ask_ollama()
    assert entry["url"] == "http://10.0.0.9:11434"
    assert entry["model"] == "qwen3:8b"
    assert mock_check.call_count == 2


@patch("kow_setup.checks.check_ollama")
def test_ask_ollama_unreachable_then_skip_retry(mock_check, monkeypatch):
    mock_check.return_value = CheckResult(service="ollama", ok=False, error="refused")
    # unreachable, decline re-entry, type a model manually
    monkeypatch.setattr(builtins, "input", _inputs(["badhost", "n", "qwen3:8b"]))
    entry = cli.ask_ollama()
    assert entry == {"mode": "remote", "url": "http://badhost:11434", "model": "qwen3:8b"}


@patch("kow_setup.checks.check_ollama")
def test_ask_ollama_blank_keeps_current_url_and_model(mock_check, monkeypatch):
    mock_check.return_value = CheckResult(
        service="ollama", ok=True, latency_ms=2, detail={"models": ["qwen3:8b", "qwen3:30b"]}
    )
    current = {"OLLAMA_HOST": "http://10.0.0.9:11434", "OLLAMA_MODEL": "qwen3:8b"}
    # blank URL -> keep current; blank model choice -> keep current
    monkeypatch.setattr(builtins, "input", _inputs(["", ""]))
    entry = cli.ask_ollama(current)
    assert entry == {"mode": "remote", "url": "http://10.0.0.9:11434", "model": "qwen3:8b"}
    mock_check.assert_called_once_with("http://10.0.0.9:11434")


def test_ask_http_service_blank_keeps_url_and_token(monkeypatch):
    current = {"STT_URL": "http://10.16.69.251:5099", "STT_TOKEN": "secret", "STT_LANGUAGE": "ru"}
    # blank url -> keep; blank token -> keep (not re-emitted); blank language -> keep
    monkeypatch.setattr(builtins, "input", _inputs(["", "", ""]))
    entry = cli.ask_http_service("stt", current)
    assert entry["url"] == "http://10.16.69.251:5099"
    assert entry["language"] == "ru"
    assert "token" not in entry  # blank leaves the stored token untouched


def test_ask_voice_blank_keeps_current(monkeypatch):
    monkeypatch.setattr(builtins, "input", _inputs([""]))
    assert cli.ask_voice({"KOW_WAKE_MODE": "both"}) == {}  # no updates -> config preserved
