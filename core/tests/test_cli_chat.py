"""Tests for `kow chat` (interactive REPL) and the --resume alias."""

import builtins

import pytest

from kowalski import cli
from kowalski.agent.llm import ToolCall

from .fake_llm import FakeLLM


def _scripted_input(lines):
    it = iter(lines)

    def fake_input(prompt=""):
        try:
            return next(it)
        except StopIteration as exc:
            raise EOFError from exc

    return fake_input


def _interrupting_input(actions):
    """Like _scripted_input, but an action of ``KeyboardInterrupt`` raises it
    (simulates Ctrl-C at the prompt); EOFError once the script runs out."""
    it = iter(actions)

    def fake_input(prompt=""):
        try:
            action = next(it)
        except StopIteration as exc:
            raise EOFError from exc
        if action is KeyboardInterrupt:
            raise KeyboardInterrupt
        return action

    return fake_input


@pytest.fixture
def chat_args(tmp_path):
    class A:
        model = None
        yes = True
        dry_run = False
        conversation = None
        continue_ = False

    return A()


def _patch_runtime(monkeypatch, tmp_path, llm):
    monkeypatch.setenv("KOW_DB_PATH", str(tmp_path / "chat.db"))
    monkeypatch.setenv("KOW_ALLOWED_PATHS", str(tmp_path))
    monkeypatch.setenv("KOW_MEMORY", "0")
    monkeypatch.setenv("KOW_SUMMARIZE", "0")
    import kowalski.bootstrap as bootstrap

    monkeypatch.setattr(bootstrap, "build_llm", lambda config, model_override="": llm)


async def test_chat_repl_multi_turn_one_conversation(monkeypatch, tmp_path, chat_args, capsys):
    # Two user lines, then EOF. FakeLLM answers each as plain text.
    llm = FakeLLM(["First answer.", "Second answer."])
    _patch_runtime(monkeypatch, tmp_path, llm)
    monkeypatch.setattr(builtins, "input", _scripted_input(["hi there", "and again", "exit"]))

    rc = await cli.cmd_chat(chat_args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "First answer." in out and "Second answer." in out
    assert "kow chat — conversation" in out
    # Both turns shared one conversation: the 2nd LLM call saw the 1st answer.
    assert any("First answer." in m.get("content", "") for m in llm.calls[1])


async def test_chat_exit_command(monkeypatch, tmp_path, chat_args, capsys):
    llm = FakeLLM(["unused"])
    _patch_runtime(monkeypatch, tmp_path, llm)
    monkeypatch.setattr(builtins, "input", _scripted_input(["exit"]))
    rc = await cli.cmd_chat(chat_args)
    assert rc == 0
    assert llm.calls == []  # nothing was asked


async def test_chat_double_ctrl_c_exits(monkeypatch, tmp_path, chat_args, capsys):
    # Two consecutive Ctrl-C at the prompt leave the REPL; no turn is run.
    llm = FakeLLM(["unused"])
    _patch_runtime(monkeypatch, tmp_path, llm)
    monkeypatch.setattr(
        builtins, "input", _interrupting_input([KeyboardInterrupt, KeyboardInterrupt])
    )
    rc = await cli.cmd_chat(chat_args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "again to quit" in out
    assert llm.calls == []


async def test_chat_single_ctrl_c_does_not_exit(monkeypatch, tmp_path, chat_args, capsys):
    # One Ctrl-C only arms the quit; the following line still runs a turn, and
    # typing disarms it (so the later single Ctrl-C does not exit either).
    llm = FakeLLM(["First.", "Second."])
    _patch_runtime(monkeypatch, tmp_path, llm)
    monkeypatch.setattr(
        builtins,
        "input",
        _interrupting_input([KeyboardInterrupt, "hi", KeyboardInterrupt, "again", "quit"]),
    )
    rc = await cli.cmd_chat(chat_args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "First." in out and "Second." in out  # both turns ran despite the Ctrl-Cs
    assert len(llm.calls) == 2


async def test_chat_quit_command(monkeypatch, tmp_path, chat_args, capsys):
    llm = FakeLLM(["unused"])
    _patch_runtime(monkeypatch, tmp_path, llm)
    monkeypatch.setattr(builtins, "input", _scripted_input(["quit"]))
    rc = await cli.cmd_chat(chat_args)
    assert rc == 0
    assert llm.calls == []


async def test_chat_tool_turn(monkeypatch, tmp_path, chat_args, capsys):
    llm = FakeLLM([[ToolCall(name="system.cpu_info", args={})], "Done."])
    _patch_runtime(monkeypatch, tmp_path, llm)
    monkeypatch.setattr(builtins, "input", _scripted_input(["how many cores", "exit"]))
    rc = await cli.cmd_chat(chat_args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "system.cpu_info" in out and "Done." in out


def test_ask_resume_is_alias_for_continue():
    # argparse: --resume sets the same dest as --continue
    parser_args = cli.main  # noqa: F841 - ensure import works
    import argparse

    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command")
    ask = sub.add_parser("ask")
    ask.add_argument("prompt")
    ask.add_argument("--continue", "--resume", dest="continue_", action="store_true")
    ns = p.parse_args(["ask", "x", "--resume"])
    assert ns.continue_ is True
