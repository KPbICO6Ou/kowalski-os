from pathlib import Path

from kowalski.tools.files import FileSearchArgs, _python_walk, build_tools


def make_tree(root: Path):
    (root / "docs").mkdir()
    (root / "docs" / "report.pdf").write_text("x")
    (root / "docs" / "notes.md").write_text("x")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "secret.pdf").write_text("x")
    (root / "presentation.pdf").write_text("x")


def test_python_walk_glob(tmp_path: Path):
    make_tree(tmp_path)
    results = _python_walk("*.pdf", tmp_path, limit=10, modified_days=None)
    names = {Path(p).name for p in results}
    assert names == {"report.pdf", "presentation.pdf"}  # hidden dir skipped


def test_python_walk_limit(tmp_path: Path):
    make_tree(tmp_path)
    results = _python_walk("*", tmp_path, limit=2, modified_days=None)
    assert len(results) == 2


async def test_search_tool_substring(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)  # force python backend
    make_tree(tmp_path)
    tool = build_tools([tmp_path])[0]
    args = FileSearchArgs(pattern="report", root=str(tmp_path))
    result = await tool.handler(args)
    assert result.ok
    assert "report.pdf" in result.content


async def test_search_outside_allowlist_rejected(tmp_path: Path):
    tool = build_tools([tmp_path / "inner"])[0]
    (tmp_path / "inner").mkdir()
    args = FileSearchArgs(pattern="x", root=str(tmp_path))
    result = await tool.handler(args)
    assert not result.ok
    assert "outside allowed" in result.content


async def test_search_no_results(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    tool = build_tools([tmp_path])[0]
    result = await tool.handler(FileSearchArgs(pattern="zzz-nothing", root=str(tmp_path)))
    assert result.ok
    assert result.data == []
