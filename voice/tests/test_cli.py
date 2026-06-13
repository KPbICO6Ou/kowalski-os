from kowvoice.cli import main


def test_demo_runs_end_to_end(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    rc = main(["demo"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "voice pipeline ready" not in out  # run_once doesn't emit ready
    assert "heard:" in out
    assert "🔊" in out
    assert "demo complete" in out


def test_demo_barge_in(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    rc = main(["demo", "--barge-in"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "barge-in" in out


def test_no_command_prints_help(capsys):
    assert main([]) == 1
