from kowindex.cli import main


def _setup_env(monkeypatch, tmp_path):
    monkeypatch.setenv("KOW_INDEX_DB", str(tmp_path / "cli.db"))
    monkeypatch.delenv("KOW_INDEX_PATHS", raising=False)


def test_cli_index_search_status(tree, tmp_path, fake_embedder, monkeypatch, capsys):
    _setup_env(monkeypatch, tmp_path)

    assert main(["index", "--paths", str(tree)], embedder=fake_embedder) == 0
    out = capsys.readouterr().out
    assert "indexed=2" in out

    assert main(["search", "wake word voice", "-n", "3"], embedder=fake_embedder) == 0
    out = capsys.readouterr().out
    first_hit = out.splitlines()[0]
    assert str(tree / "voice.md") in first_hit

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "files" in out and "vec_backend" in out


def test_cli_search_empty_index(tmp_path, fake_embedder, monkeypatch, capsys):
    _setup_env(monkeypatch, tmp_path)
    assert main(["search", "anything"], embedder=fake_embedder) == 0
    assert "no results" in capsys.readouterr().out


def test_cli_no_command_prints_help(capsys):
    assert main([]) == 1
    assert "kow-index" in capsys.readouterr().out


def test_cli_index_respects_kow_index_paths(tree, tmp_path, fake_embedder, monkeypatch, capsys):
    _setup_env(monkeypatch, tmp_path)
    monkeypatch.setenv("KOW_INDEX_PATHS", str(tree))
    assert main(["index"], embedder=fake_embedder) == 0
    assert "indexed=2" in capsys.readouterr().out
