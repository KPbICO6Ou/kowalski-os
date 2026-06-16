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

import importlib.util
import re
import shutil
from pathlib import Path

# openWakeWord ships/downloads these; a phrase outside the set needs training.
PRETRAINED = {"alexa", "hey_jarvis", "hey_mycroft", "hey_rhasspy", "timer", "weather"}
# python modules needed for training, beyond the inference [mic] stack
TRAIN_REQUIREMENTS = ("torch", "torchaudio", "openwakeword")


def slugify(phrase: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", phrase.strip().lower()).strip("_")
    return slug or "wakeword"


def is_pretrained(phrase: str) -> bool:
    return phrase.strip().lower() in PRETRAINED


def model_path_for(phrase: str, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (Path.home() / ".config" / "kowalski" / "wake")
    return out_dir / f"{slugify(phrase)}.onnx"


def missing_requirements() -> list[str]:
    return [m for m in TRAIN_REQUIREMENTS if importlib.util.find_spec(m) is None]


def setup_instructions() -> str:
    return (
        "Wake-word training needs the openWakeWord training stack (heavy, "
        "minutes on CPU):\n"
        "  pip install -e 'voice[mic]'\n"
        "  pip install torch torchaudio            # CPU build is fine; GPU is faster\n"
        "  git clone https://github.com/rhasspy/piper-sample-generator  # positive samples\n"
        "  # + openWakeWord's background/negative feature set (see its docs)\n"
        "Then run the openWakeWord training notebook and register the result:\n"
        "  kow-voice train <phrase> --model <model.onnx>"
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
            f"then bring the model back and run:\n"
            f"  kow-voice train {phrase} --model {slugify(phrase)}.onnx"
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
        dest = model_path_for(phrase, out_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dest.resolve():
            shutil.copyfile(src, dest)
            # openWakeWord exports split the graph (.onnx) from its weights
            # (.onnx.data); carry the sidecar across or the model won't load.
            sidecar = Path(str(src) + ".data")
            if sidecar.exists():
                shutil.copyfile(sidecar, Path(str(dest) + ".data"))
        _merge_conf({"KOW_WAKE_MODEL": str(dest)}, config_path)
        on_text(f"registered wake model: {dest}\n"
                "(KOW_WAKE_MODEL set, wake mode = both) — try: kow-voice run")
        return 0

    # custom phrase, no model yet -> training is required
    missing = missing_requirements()
    if missing:
        on_text(f"no model for '{phrase}', and the training stack is missing "
                f"({', '.join(missing)}).\n" + setup_instructions())
    else:
        on_text(f"no model for '{phrase}'. Training execution is verified on "
                "hardware; run the openWakeWord notebook, then:\n"
                f"  kow-voice train {phrase} --model <model.onnx>")
    return 2


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="kow-voice train", description="prepare a wake word")
    parser.add_argument("phrase", help="wake phrase, e.g. kowalski or hey_jarvis")
    parser.add_argument("--model", help="path to an already-trained .onnx/.tflite model")
    parser.add_argument("--out-dir", type=Path, help="where to store the model / bundle")
    parser.add_argument("--prepare", action="store_true",
                        help="build a portable training bundle for a GPU box (no training here)")
    parser.add_argument("--samples", type=int, help="positive synthetic clips (default 50000)")
    parser.add_argument("--steps", type=int, help="training steps (default 50000)")
    args = parser.parse_args(argv)
    return run_train(args.phrase, model=args.model, out_dir=args.out_dir,
                     prepare=args.prepare, n_samples=args.samples, steps=args.steps)
