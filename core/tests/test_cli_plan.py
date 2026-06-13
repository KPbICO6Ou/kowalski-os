"""End-to-end CLI test for `kow ask --plan` using a scripted FakeLLM.

build_llm is patched to return the FakeLLM; everything else (config, store,
registry, conversation persistence) is the real in-process stack against a
tmp database, so this also exercises _run_planner_turn's persistence wiring."""

from __future__ import annotations

from pathlib import Path

import kowalski.cli as cli
from kowalski.config import Config

from .fake_llm import FakeLLM


def _tmp_config(tmp_path: Path) -> Config:
    return Config(
        dict(
            KOW_DB_PATH=str(tmp_path / "kow.db"),
            KOW_ALLOWED_PATHS=str(tmp_path),
            KOW_MAX_ITERATIONS="6",
            KOW_TOOL_TIMEOUT="5",
            KOW_AUTO_ALLOW_NETWORK="0",
            OLLAMA_HOST="http://127.0.0.1:11434",
            OLLAMA_MODEL="test",
        )
    )


def test_cli_plan_renders_plan_and_steps(tmp_path, monkeypatch, capsys):
    llm = FakeLLM(['["do A", "do B"]', "Did A.", "Did B.", "Final summary."])
    monkeypatch.setattr(cli.Config, "load", classmethod(lambda cls: _tmp_config(tmp_path)))
    monkeypatch.setattr("kowalski.bootstrap.build_llm", lambda config, model_override="": llm)

    rc = cli.main(["ask", "--plan", "--yes", "the goal"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Plan:" in out
    assert "1. do A" in out
    assert "2. do B" in out
    assert "step 1/2: do A" in out
    assert "step 2/2: do B" in out
    assert "Final summary." in out


def test_cli_plan_off_by_default_uses_react(tmp_path, monkeypatch, capsys):
    # A single text turn = a plain ReAct answer; no Plan: header should appear.
    llm = FakeLLM(["The answer is 42."])
    monkeypatch.setattr(cli.Config, "load", classmethod(lambda cls: _tmp_config(tmp_path)))
    monkeypatch.setattr("kowalski.bootstrap.build_llm", lambda config, model_override="": llm)

    rc = cli.main(["ask", "--yes", "the goal"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Plan:" not in out
    assert "42" in out
