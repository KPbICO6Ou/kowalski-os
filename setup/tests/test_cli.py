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


def test_choose_model_prompt_shows_current_name(monkeypatch):
    seen = []

    def recording_input(prompt=""):
        seen.append(prompt)
        return ""

    monkeypatch.setattr(builtins, "input", recording_input)
    cli._choose_model(["a", "qwen3:8b"], current="qwen3:8b")
    assert "keep current (qwen3:8b)" in seen[-1]


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


@patch("kow_setup.checks.check_stt")
def test_ask_http_service_normalizes_schemeless_url(mock_stt, monkeypatch):
    # The reported bug: 'host:port' with no scheme must become a valid http URL.
    mock_stt.return_value = CheckResult(service="stt", ok=True, latency_ms=5)
    monkeypatch.setattr(builtins, "input", _inputs(["10.16.69.251:5051", "", "ru"]))
    entry = cli.ask_http_service("stt")
    assert entry["url"] == "http://10.16.69.251:5051"
    assert entry["language"] == "ru"
    mock_stt.assert_called_once()


@patch("kow_setup.checks.check_tts")
def test_ask_http_service_adds_default_port(mock_tts, monkeypatch):
    mock_tts.return_value = CheckResult(service="tts", ok=True, latency_ms=2)
    monkeypatch.setattr(builtins, "input", _inputs(["10.16.69.251", ""]))
    entry = cli.ask_http_service("tts")
    assert entry["url"] == "http://10.16.69.251:5052"  # tts default port


def test_suggested_host_from_ollama_answer():
    raw = {"ollama": {"mode": "remote", "url": "http://10.16.69.251:11434"}}
    assert cli._suggested_host(raw, {}) == "10.16.69.251"


def test_suggested_host_falls_back_to_current():
    assert cli._suggested_host({}, {"OLLAMA_HOST": "http://10.0.0.5:11434"}) == "10.0.0.5"


def test_suggested_host_empty_when_unknown():
    assert cli._suggested_host({}, {}) == ""


@patch("kow_setup.checks.check_stt")
def test_ask_http_service_suggests_ollama_host_and_port(mock_stt, monkeypatch):
    # blank URL accepts the suggested <ollama host>:<stt default port 5051>
    mock_stt.return_value = CheckResult(service="stt", ok=True, latency_ms=1)
    monkeypatch.setattr(builtins, "input", _inputs(["", "", ""]))
    entry = cli.ask_http_service("stt", default_host="10.16.69.251")
    assert entry["url"] == "http://10.16.69.251:5051"


@patch("kow_setup.checks.check_tts")
def test_ask_http_service_suggested_url_in_prompt(mock_tts, monkeypatch):
    mock_tts.return_value = CheckResult(service="tts", ok=True, latency_ms=1)
    seen = []

    def recording_input(prompt=""):
        seen.append(prompt)
        return ""

    monkeypatch.setattr(builtins, "input", recording_input)
    cli.ask_http_service("tts", default_host="10.16.69.251")
    assert "10.16.69.251:5052" in seen[0]  # address shown in the URL prompt


@patch("kow_setup.checks.check_stt")
def test_ask_http_service_blank_keeps_url_and_token(mock_stt, monkeypatch):
    mock_stt.return_value = CheckResult(service="stt", ok=True, latency_ms=1)
    current = {"STT_URL": "http://10.16.69.251:5099", "STT_TOKEN": "secret", "STT_LANGUAGE": "ru"}
    # blank url -> keep; blank token -> keep (not re-emitted); blank language -> keep
    monkeypatch.setattr(builtins, "input", _inputs(["", "", ""]))
    entry = cli.ask_http_service("stt", current)
    assert entry["url"] == "http://10.16.69.251:5099"
    assert entry["language"] == "ru"
    assert "token" not in entry  # blank leaves the stored token untouched
    # the stored token is still used for the probe
    assert mock_stt.call_args.args[1] == "secret"


@patch("kow_setup.checks.check_tts")
def test_ask_http_service_reenter_after_failed_check(mock_tts, monkeypatch):
    # bad port fails the probe -> [r]e-enter (blank default) -> good port passes
    mock_tts.side_effect = [
        CheckResult(service="tts", ok=False, error="Connection refused"),
        CheckResult(service="tts", ok=True, latency_ms=3),
    ]
    monkeypatch.setattr(
        builtins, "input", _inputs(["10.16.69.251:5052", "", "", "10.16.69.251:5000", ""])
    )
    entry = cli.ask_http_service("tts")
    assert entry["url"] == "http://10.16.69.251:5000"
    assert mock_tts.call_count == 2


@patch("kow_setup.checks.check_tts")
def test_ask_http_service_skip_after_failed_check(mock_tts, monkeypatch):
    mock_tts.return_value = CheckResult(service="tts", ok=False, error="refused")
    monkeypatch.setattr(builtins, "input", _inputs(["10.16.69.251:5052", "", "s"]))
    assert cli.ask_http_service("tts") == {"mode": "skip"}


@patch("kow_setup.checks.check_tts")
def test_ask_http_service_keep_anyway_after_failed_check(mock_tts, monkeypatch):
    mock_tts.return_value = CheckResult(service="tts", ok=False, error="refused")
    monkeypatch.setattr(builtins, "input", _inputs(["10.16.69.251:5052", "", "a"]))
    entry = cli.ask_http_service("tts")
    assert entry == {"mode": "remote", "url": "http://10.16.69.251:5052"}


def test_ask_voice_blank_keeps_current(monkeypatch):
    monkeypatch.setattr(builtins, "input", _inputs([""]))
    assert cli.ask_voice({"KOW_WAKE_MODE": "both"}) == {}  # no updates -> config preserved
