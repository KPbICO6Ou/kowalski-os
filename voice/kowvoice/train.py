"""`kow-voice train`: get a custom openWakeWord wake word ready.

A bespoke phrase like "kowalski" has no pretrained openWakeWord model, so one
must be trained from synthetic speech. That training is heavy (PyTorch + a piper
sample generator + background audio) and runs for many minutes on CPU, so it is
verified on hardware. This command does the deterministic, verifiable parts:

  * register an already-trained model:  kow-voice train kowalski --model k.onnx
  * a pretrained phrase:                kow-voice train hey_jarvis
  * otherwise: print exactly how to train, then re-run with --model

In every success case it wires the model/word into kowalski.conf (KOW_WAKE_MODEL/
KOW_WAKE_WORD + KOW_WAKE_MODE=both) so `kow-voice run`/`chat` pick it up. The
kow-setup wizard calls this at the end when a custom wake word was chosen."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

# openWakeWord ships/downloads these; a phrase outside the set needs training.
PRETRAINED = {"alexa", "hey_jarvis", "hey_mycroft", "hey_rhasspy", "timer", "weather"}


def slugify(phrase: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", phrase.strip().lower()).strip("_")
    return slug or "wakeword"


def is_pretrained(phrase: str) -> bool:
    return phrase.strip().lower() in PRETRAINED


def model_path_for(phrase: str, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (Path.home() / ".config" / "kowalski" / "wake")
    return out_dir / f"{slugify(phrase)}.onnx"


def train_instructions(phrase: str) -> str:
    """The inline 3-stage recipe for training a custom wake word: prepare a
    bundle here, run it on a CUDA GPU box, register the result back here. Printed
    verbatim so a user with no GPU sees the exact commands without opening a doc."""
    slug = slugify(phrase)
    return (
        f"No model for the wake word '{phrase}' yet — a custom phrase has no "
        "pretrained openWakeWord model, so it must be trained on a CUDA GPU "
        "(this box has none). Three steps, two machines:\n"
        "\n"
        "  1. here — build a portable training bundle (needs nothing heavy):\n"
        f"       kow-voice train {phrase} --prepare\n"
        f"     -> {slug}-wakeword-train.tar.gz  (config + train.sh + README)\n"
        "\n"
        "  2. on a CUDA GPU box (Linux/WSL2 + NVIDIA, Python >=3.10, git):\n"
        f"       tar xzf {slug}-wakeword-train.tar.gz\n"
        f"       cd {slug}-wakeword-train && ./train.sh\n"
        f"     -> {slug}-model.tar.gz  (one archive, carry it back)\n"
        "\n"
        "  3. back here — register the trained model:\n"
        f"       kow-voice train {phrase} --model {slug}-model.tar.gz\n"
        f"     -> copied into ~/.config/kowalski/wake/, KOW_WAKE_MODE=both"
    )


def _merge_conf(updates: dict[str, str], config_path: Path | None = None) -> Path:
    """Merge KEY=VALUE updates into kowalski.conf, preserving every other key."""
    from .settings import _kowalski_conf_path, _parse_conf

    path = Path(config_path) if config_path else _kowalski_conf_path()
    values = _parse_conf(path)
    values.update(updates)
    if values.get("KOW_WAKE_MODE", "push_to_talk") == "push_to_talk":
        values["KOW_WAKE_MODE"] = "both"  # a wake word is useless in push-to-talk only
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"{k}={v}" for k, v in sorted(values.items())) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def resolve_model_source(src: Path):
    """Locate the wake model to register from a --model path. Accepts either a
    bare .onnx/.tflite file or a .tar.gz/.tgz bundle that packs the model (+ its
    .onnx.data sidecar) — train.sh now emits one archive instead of two files.

    Returns (model_path, sidecar_path_or_None, tempdir_or_None); the caller must
    rmtree tempdir when set. (None, None, tempdir) if no model is inside."""
    import tarfile

    if not tarfile.is_tarfile(src):  # a plain .onnx/.tflite path
        sidecar = Path(str(src) + ".data")
        return src, (sidecar if sidecar.exists() else None), None

    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="kow-wake-"))
    with tarfile.open(src) as tar:
        tar.extractall(tmp, filter="data")  # filter guards against path traversal
    onnx = next(iter(sorted(tmp.rglob("*.onnx"))), None)
    if onnx is None:
        onnx = next(iter(sorted(tmp.rglob("*.tflite"))), None)
        return onnx, None, tmp
    sidecar = Path(str(onnx) + ".data")
    return onnx, (sidecar if sidecar.exists() else None), tmp


def run_train(
    phrase: str,
    *,
    model: str | None = None,
    out_dir: Path | None = None,
    config_path: Path | None = None,
    on_text=print,
    prepare: bool = False,
    n_samples: int | None = None,
    steps: int | None = None,
) -> int:
    """Returns 0 when a model/word was registered or a bundle was prepared, 2
    when training is still required (with guidance)."""
    phrase = (phrase or "").strip()
    if not phrase:
        on_text("usage: kow-voice train <phrase> [--model file.onnx | --prepare]")
        return 2

    if prepare:
        from . import train_bundle

        opts = {k: v for k, v in (("n_samples", n_samples), ("steps", steps)) if v}
        path = train_bundle.write_bundle(phrase, out_dir=out_dir, **opts)
        on_text(
            f"prepared wake-word training bundle: {path}\n"
            "Carry it to a CUDA GPU box and run ./train.sh (see README.md inside), "
            f"then bring the one model archive back and run:\n"
            f"  kow-voice train {phrase} --model {slugify(phrase)}-model.tar.gz"
        )
        return 0

    if is_pretrained(phrase):
        _merge_conf({"KOW_WAKE_WORD": phrase}, config_path)
        on_text(f"'{phrase}' is a pretrained openWakeWord model — configured "
                f"(KOW_WAKE_WORD={phrase}, wake mode = both).")
        return 0

    if model:
        src = Path(model).expanduser()
        if not src.exists():
            on_text(f"model file not found: {src}")
            return 2
        onnx, sidecar, tmp = resolve_model_source(src)
        if onnx is None:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
            on_text(f"no .onnx/.tflite model found inside {src.name}")
            return 2
        try:
            dest = model_path_for(phrase, out_dir)
            if onnx.suffix == ".tflite":
                dest = dest.with_suffix(".tflite")
            dest.parent.mkdir(parents=True, exist_ok=True)
            if onnx.resolve() != dest.resolve():
                shutil.copyfile(onnx, dest)
                # openWakeWord exports split the graph (.onnx) from its weights
                # (.onnx.data); carry the sidecar across or the model won't load.
                if sidecar:
                    shutil.copyfile(sidecar, Path(str(dest) + ".data"))
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
        _merge_conf({"KOW_WAKE_MODEL": str(dest)}, config_path)
        on_text(f"registered wake model: {dest}\n"
                "(KOW_WAKE_MODEL set, wake mode = both) — try: kow-voice run")
        return 0

    # custom phrase, no model yet -> training is required (on a GPU box)
    on_text(train_instructions(phrase))
    return 2


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="kow-voice train", description="prepare a wake word")
    parser.add_argument("phrase", help="wake phrase, e.g. kowalski or hey_jarvis")
    parser.add_argument("--model",
                        help="trained model to register: a .onnx/.tflite file or the "
                             "<slug>-model.tar.gz that train.sh emits")
    parser.add_argument("--out-dir", type=Path, help="where to store the model / bundle")
    parser.add_argument("--prepare", action="store_true",
                        help="build a portable training bundle for a GPU box (no training here)")
    parser.add_argument("--samples", type=int, help="positive synthetic clips (default 50000)")
    parser.add_argument("--steps", type=int, help="training steps (default 50000)")
    args = parser.parse_args(argv)
    return run_train(args.phrase, model=args.model, out_dir=args.out_dir,
                     prepare=args.prepare, n_samples=args.samples, steps=args.steps)
