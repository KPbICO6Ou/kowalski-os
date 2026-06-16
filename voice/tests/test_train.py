"""kow-voice train: model registration, config wiring, and training guidance."""

from kowvoice import train


def test_slugify():
    assert train.slugify("Kowalski") == "kowalski"
    assert train.slugify("hey there!") == "hey_there"


def test_is_pretrained():
    assert train.is_pretrained("hey_jarvis")
    assert not train.is_pretrained("kowalski")


def test_model_path_for(tmp_path):
    assert train.model_path_for("Kowalski", tmp_path) == tmp_path / "kowalski.onnx"


def _conf(tmp_path):
    return tmp_path / "kowalski.conf"


def test_register_existing_model_writes_config(tmp_path):
    src = tmp_path / "k.onnx"
    src.write_bytes(b"onnx")
    conf = _conf(tmp_path)
    out_dir = tmp_path / "wake"
    lines = []
    rc = train.run_train(
        "kowalski", model=str(src), out_dir=out_dir, config_path=conf, on_text=lines.append
    )
    assert rc == 0
    dest = out_dir / "kowalski.onnx"
    assert dest.exists()  # model copied into place
    body = conf.read_text()
    assert f"KOW_WAKE_MODEL={dest}" in body
    assert "KOW_WAKE_MODE=both" in body  # push-to-talk-only would be useless


def test_register_missing_model_file_fails(tmp_path):
    rc = train.run_train("kowalski", model=str(tmp_path / "nope.onnx"),
                         config_path=_conf(tmp_path), on_text=lambda *_: None)
    assert rc == 2


def test_pretrained_phrase_just_configures(tmp_path):
    conf = _conf(tmp_path)
    rc = train.run_train("hey_jarvis", config_path=conf, on_text=lambda *_: None)
    assert rc == 0
    body = conf.read_text()
    assert "KOW_WAKE_WORD=hey_jarvis" in body
    assert "KOW_WAKE_MODE=both" in body


def test_custom_phrase_without_model_guides(tmp_path):
    lines = []
    rc = train.run_train("kowalski", config_path=_conf(tmp_path), on_text=lines.append)
    assert rc == 2
    out = "\n".join(lines)
    assert "kowalski" in out
    # either the training stack is missing or it points at --model
    assert "kow-voice train" in out


def test_merge_conf_preserves_other_keys(tmp_path):
    conf = _conf(tmp_path)
    conf.write_text("STT_URL=http://10.0.0.5:5051\nKOW_WAKE_MODE=push_to_talk\n")
    train._merge_conf({"KOW_WAKE_MODEL": "/m/k.onnx"}, conf)
    body = conf.read_text()
    assert "STT_URL=http://10.0.0.5:5051" in body  # untouched
    assert "KOW_WAKE_MODEL=/m/k.onnx" in body
    assert "KOW_WAKE_MODE=both" in body  # upgraded from push_to_talk
