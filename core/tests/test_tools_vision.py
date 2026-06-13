from pathlib import Path

import pytest

from kowalski.config import Config
from kowalski.vision.capture import MockScreenCapturer
from kowalski.vision.describe import MockVisionModel
from kowalski.tools.vision import build_vision_tools


def _cfg() -> Config:
    return Config(values={"OLLAMA_HOST": "http://127.0.0.1:11434"})


def _tool(tools, name: str):
    return next(t for t in tools if t.name == name)


@pytest.fixture
def capturer() -> MockScreenCapturer:
    return MockScreenCapturer(png=b"\x89PNG-mock-screenshot-bytes")


@pytest.fixture
def model() -> MockVisionModel:
    return MockVisionModel(reply="A terminal and a browser are open.")


def test_tools_are_read_tools(capturer, model):
    tools = build_vision_tools(_cfg(), capturer=capturer, model=model)
    names = {t.name for t in tools}
    assert names == {"screen.capture", "screen.describe"}
    for t in tools:
        assert t.risk == "read"


async def test_capture_writes_bytes_and_reports_size(tmp_path: Path, capturer, model):
    tools = build_vision_tools(_cfg(), capturer=capturer, model=model)
    t = _tool(tools, "screen.capture")
    out = tmp_path / "shot.png"

    result = await t.handler(t.args_model(path=str(out)))

    assert result.ok
    assert out.exists()
    assert out.read_bytes() == capturer.png
    assert result.data["path"] == str(out)
    assert result.data["bytes"] == len(capturer.png)
    assert capturer.calls == 1


async def test_capture_default_path(capturer, model):
    tools = build_vision_tools(_cfg(), capturer=capturer, model=model)
    t = _tool(tools, "screen.capture")

    result = await t.handler(t.args_model())

    assert result.ok
    saved = Path(result.data["path"])
    try:
        assert saved.exists()
        assert saved.read_bytes() == capturer.png
    finally:
        saved.unlink(missing_ok=True)


async def test_describe_returns_mock_and_passes_image_and_prompt(capturer, model):
    tools = build_vision_tools(_cfg(), capturer=capturer, model=model)
    t = _tool(tools, "screen.describe")

    result = await t.handler(t.args_model(prompt="Describe the windows."))

    assert result.ok
    assert result.content == "A terminal and a browser are open."
    assert result.data["description"] == "A terminal and a browser are open."
    # the model received the captured screenshot bytes and the prompt
    assert model.received_image
    assert model.last_png == capturer.png
    assert model.last_prompt == "Describe the windows."
    assert capturer.calls == 1


async def test_describe_default_prompt(capturer, model):
    tools = build_vision_tools(_cfg(), capturer=capturer, model=model)
    t = _tool(tools, "screen.describe")

    result = await t.handler(t.args_model())

    assert result.ok
    assert model.last_prompt == "What is on the screen right now? Be concise."


async def test_capture_error_path_returns_not_ok(tmp_path: Path, model):
    class FailingCapturer:
        async def capture(self) -> bytes:
            raise RuntimeError("no screenshot tool found — install maim")

    tools = build_vision_tools(_cfg(), capturer=FailingCapturer(), model=model)
    t = _tool(tools, "screen.capture")

    result = await t.handler(t.args_model(path=str(tmp_path / "x.png")))

    assert not result.ok
    assert "no screenshot tool found" in result.content
    assert not (tmp_path / "x.png").exists()


async def test_describe_capture_error_path(capturer, model):
    class FailingCapturer:
        async def capture(self) -> bytes:
            raise RuntimeError("display unavailable")

    tools = build_vision_tools(_cfg(), capturer=FailingCapturer(), model=model)
    t = _tool(tools, "screen.describe")

    result = await t.handler(t.args_model())

    assert not result.ok
    assert "display unavailable" in result.content
    assert model.calls == 0


async def test_describe_model_error_path(capturer):
    class FailingModel:
        async def describe(self, png: bytes, prompt: str) -> str:
            raise RuntimeError("ollama not reachable")

    tools = build_vision_tools(_cfg(), capturer=capturer, model=FailingModel())
    t = _tool(tools, "screen.describe")

    result = await t.handler(t.args_model())

    assert not result.ok
    assert "ollama not reachable" in result.content
