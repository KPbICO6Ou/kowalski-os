from pathlib import Path

from kowalski.config import DEFAULTS, Config, parse_conf


def test_parse_conf_basics():
    text = """
# comment
OLLAMA_MODEL=qwen2.5:14b
QUOTED="hello world"
SINGLE='x'
SPACES =  padded
BROKEN LINE WITHOUT EQUALS IS SKIPPED?  no-wait-this-has-none
"""
    values = parse_conf(text)
    assert values["OLLAMA_MODEL"] == "qwen2.5:14b"
    assert values["QUOTED"] == "hello world"
    assert values["SINGLE"] == "x"
    assert values["SPACES"] == "padded"


def test_defaults_when_no_file(tmp_path: Path):
    config = Config.load(tmp_path / "missing.conf")
    assert config.get("OLLAMA_HOST") == DEFAULTS["OLLAMA_HOST"]


def test_file_overrides_defaults(tmp_path: Path):
    conf = tmp_path / "kowalski.conf"
    conf.write_text("OLLAMA_MODEL=llama3.1\n")
    config = Config.load(conf)
    assert config.get("OLLAMA_MODEL") == "llama3.1"


def test_env_overrides_file(tmp_path: Path, monkeypatch):
    conf = tmp_path / "kowalski.conf"
    conf.write_text("OLLAMA_MODEL=from-file\n")
    monkeypatch.setenv("OLLAMA_MODEL", "from-env")
    config = Config.load(conf)
    assert config.get("OLLAMA_MODEL") == "from-env"


def test_allowed_paths_parsing(tmp_path: Path):
    config = Config({"KOW_ALLOWED_PATHS": f"{tmp_path}:~"})
    paths = config.allowed_paths
    assert tmp_path.resolve() in paths
    assert Path.home().resolve() in paths


def test_typed_getters():
    config = Config({"N": "42", "B": "true", "P": "~/x"})
    assert config.get_int("N") == 42
    assert config.get_bool("B") is True
    assert config.get_path("P") == Path("~/x").expanduser()
