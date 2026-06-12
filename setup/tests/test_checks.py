from unittest.mock import MagicMock, patch

from kow_setup.checks import check_ollama, check_stt, check_tts


def fake_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


@patch("kow_setup.checks.requests.get")
def test_ollama_ok(mock_get):
    mock_get.return_value = fake_response({"models": [{"name": "qwen2.5:14b"}]})
    result = check_ollama("http://h:11434")
    assert result.ok
    assert result.detail["models"] == ["qwen2.5:14b"]
    assert result.latency_ms is not None


@patch("kow_setup.checks.requests.get", side_effect=ConnectionError("refused"))
def test_ollama_unreachable(mock_get):
    result = check_ollama("http://h:11434")
    assert not result.ok
    assert "refused" in result.error


@patch("kow_setup.checks.requests.get")
def test_stt_no_workers_fails(mock_get):
    mock_get.return_value = fake_response({"available": 0})
    result = check_stt("http://h:5099")
    assert not result.ok
    assert "no STT workers" in result.error


@patch("kow_setup.checks.requests.get")
def test_stt_token_sent(mock_get):
    mock_get.return_value = fake_response({"available": 2})
    result = check_stt("http://h:5099", token="secret")
    assert result.ok
    headers = mock_get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer secret"


@patch("kow_setup.checks.requests.get")
def test_tts_ok(mock_get):
    mock_get.return_value = fake_response({"engine": "silerotts"})
    result = check_tts("http://h:5000")
    assert result.ok
