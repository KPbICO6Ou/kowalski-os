"""ClipboardWatcher and kow-clip: no real clipboard, no real daemon."""

from __future__ import annotations

from kowui import clipboard
from kowui.clipboard import ClipboardWatcher, read_clipboard

LONG = "x" * 100
LONG2 = "y" * 100
ANSWER = "I could summarize this for you."


class FakeClient:
    """Stand-in OmniClient whose ask() yields a scripted DoneEvent."""

    def __init__(self, answer: str = ANSWER) -> None:
        self.answer = answer
        self.calls: list[tuple[str, str | None]] = []

    async def ask(self, prompt, conversation_id=None):
        self.calls.append((prompt, conversation_id))
        yield {"event": "TokenEvent", "text": "..."}
        yield {"event": "DoneEvent", "answer": self.answer}


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, text: str, answer: str) -> None:
        self.calls.append((text, answer))


def _watcher(client, on_suggestion, text, *, min_len=80, cooldown=5.0, clock=None):
    return ClipboardWatcher(
        client,
        on_suggestion,
        min_len=min_len,
        cooldown=cooldown,
        reader=lambda: text,
        clock=clock,
    )


def test_read_clipboard_none_when_no_tool(monkeypatch):
    monkeypatch.setattr(clipboard.shutil, "which", lambda _name: None)
    assert read_clipboard() is None


async def test_cycle_fires_for_meaningful_text():
    client = FakeClient()
    rec = Recorder()
    watcher = _watcher(client, rec, LONG, clock=lambda: 0.0)

    assert await watcher._cycle() is True
    assert rec.calls == [(LONG, ANSWER)]
    assert LONG in client.calls[0][0]


async def test_cycle_skips_short_text():
    client = FakeClient()
    rec = Recorder()
    watcher = _watcher(client, rec, "too short", clock=lambda: 0.0)

    assert await watcher._cycle() is False
    assert rec.calls == []
    assert client.calls == []


async def test_cycle_skips_file_uri():
    client = FakeClient()
    rec = Recorder()
    watcher = _watcher(client, rec, "file://" + LONG, clock=lambda: 0.0)

    assert await watcher._cycle() is False
    assert rec.calls == []


async def test_cycle_skips_unchanged_text():
    client = FakeClient()
    rec = Recorder()
    watcher = _watcher(client, rec, LONG, clock=lambda: 0.0)

    assert await watcher._cycle() is True
    # Second cycle: same text, must not fire again.
    assert await watcher._cycle() is False
    assert len(rec.calls) == 1


async def test_cycle_respects_cooldown():
    client = FakeClient()
    rec = Recorder()
    now = {"t": 0.0}
    watcher = _watcher(client, rec, LONG, cooldown=5.0, clock=lambda: now["t"])

    assert await watcher._cycle() is True
    # New text but still within cooldown window -> no fire.
    watcher._reader = lambda: LONG2
    now["t"] = 1.0
    assert await watcher._cycle() is False
    assert len(rec.calls) == 1

    # Past cooldown -> fires again.
    watcher._reader = lambda: LONG2 + "z"
    now["t"] = 10.0
    assert await watcher._cycle() is True
    assert len(rec.calls) == 2


async def test_cycle_robust_on_reader_error():
    client = FakeClient()
    rec = Recorder()

    def boom():
        raise RuntimeError("clipboard blew up")

    watcher = ClipboardWatcher(client, rec, reader=boom, clock=lambda: 0.0)
    assert await watcher._cycle() is False
    assert rec.calls == []


def test_main_once_returns_zero(monkeypatch):
    # Fake the client so no real socket is touched; short clipboard text means
    # main(--once) runs one harmless cycle and exits 0.
    monkeypatch.setattr(clipboard, "OmniClient", lambda socket_path=None: FakeClient())
    monkeypatch.setattr(clipboard, "read_clipboard", lambda: "short")
    assert clipboard.main(["--once"]) == 0


def test_main_once_emits_for_meaningful(monkeypatch, capsys):
    client = FakeClient()
    monkeypatch.setattr(clipboard, "OmniClient", lambda socket_path=None: client)
    monkeypatch.setattr(clipboard, "read_clipboard", lambda: LONG)

    async def fake_notify(title, body):
        return True

    import kowalski.platform as platform

    monkeypatch.setattr(platform, "notify", fake_notify)
    assert clipboard.main(["--once"]) == 0
    out = capsys.readouterr().out
    assert ANSWER in out
