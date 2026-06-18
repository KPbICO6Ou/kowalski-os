"""kow-voice wake-fit: train a personal openWakeWord model on the samples captured
by kow-voice wake-record. Keeps openWakeWord's feature extractor (melspectrogram ->
embedding, the [16,96] input) and trains a small classifier on the user's own
recordings — heavily augmented (random position in the window, noise, gain, speed)
— against a large bank of real negative features. CPU-only, runs on this box. The
synthetic Piper pipeline produced dead models and can't do non-English; real voice
fixes both."""

from __future__ import annotations

import sys
from pathlib import Path

# Real negative embedding frames (openWakeWord's false-positive validation set).
NEG_FEATURES_URL = (
    "https://huggingface.co/datasets/davidscripka/openwakeword_features"
    "/resolve/main/validation_set_features.npy"
)
WIN = 16          # embedding frames the model sees ([WIN, 96])
BUF_SAMPLES = 35200   # ~2.2 s @ 16 kHz -> >= WIN frames from embed_clips


def _load_wavs(folder: Path):
    import wave

    import numpy as np

    clips = []
    for p in sorted(folder.glob("*.wav")):
        w = wave.open(str(p))
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        if w.getnchannels() == 2:
            x = x[::2]
        if x.size:
            clips.append(x.astype(np.float32))
    return clips


def _augment(word, noises, rng):
    """One augmented 16-bit buffer: speed/gain-perturbed word placed at a random
    offset in a BUF_SAMPLES window, with optional additive noise at a random SNR."""
    import numpy as np

    speed = rng.uniform(0.9, 1.1)
    n = max(1, int(word.size / speed))
    w = np.interp(np.linspace(0, word.size - 1, n), np.arange(word.size), word)
    w = w * rng.uniform(0.5, 1.4)

    buf = np.zeros(BUF_SAMPLES, dtype=np.float32)
    w = w[:BUF_SAMPLES]
    off = int(rng.integers(0, BUF_SAMPLES - w.size + 1)) if w.size < BUF_SAMPLES else 0
    buf[off:off + w.size] += w

    if noises and rng.random() < 0.85:
        noise = noises[int(rng.integers(len(noises)))]
        tiled = np.resize(noise, BUF_SAMPLES).astype(np.float32)
        wr = np.sqrt(np.mean(w ** 2)) + 1e-9
        nr = np.sqrt(np.mean(tiled ** 2)) + 1e-9
        snr = rng.uniform(3.0, 25.0)
        buf += tiled * (wr / nr) / (10 ** (snr / 20.0))
    return np.clip(buf, -32768, 32767).astype(np.int16)


def _net(layer_dim: int = 128):
    import torch.nn as nn

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.flatten = nn.Flatten()
            self.layer1 = nn.Linear(WIN * 96, layer_dim)
            self.relu1 = nn.ReLU()
            self.layernorm1 = nn.LayerNorm(layer_dim)
            self.fcn = nn.Linear(layer_dim, layer_dim)
            self.relu2 = nn.ReLU()
            self.layernorm2 = nn.LayerNorm(layer_dim)
            self.last = nn.Linear(layer_dim, 1)
            self.act = nn.Sigmoid()

        def forward(self, x):
            x = self.relu1(self.layernorm1(self.layer1(self.flatten(x))))
            x = self.relu2(self.layernorm2(self.fcn(x)))
            return self.act(self.last(x))

    return Net()


def verify_recordings(slug: str, model_path) -> dict:
    """Score the recorded positives/negatives through the model with openWakeWord
    exactly as the live listener would (peak score per clip). Returns
    {"pos": [...], "neg": [...]} — the real end-to-end check, not held-out windows."""
    import wave

    import numpy as np

    from openwakeword.model import Model

    from .wake_record import samples_dir

    model = Model(wakeword_models=[str(model_path)], inference_framework="onnx")

    def peak(path) -> float:
        wav = wave.open(str(path))
        x = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
        if wav.getnchannels() == 2:
            x = x[::2]
        if hasattr(model, "reset"):
            model.reset()
        best = 0.0
        for i in range(0, max(1, x.size - 1280), 1280):
            scores = model.predict(x[i:i + 1280])
            if scores:
                best = max(best, max(scores.values()))
        return best

    base = samples_dir(slug)
    pos = [peak(p) for p in sorted((base / "positive").glob("*.wav"))]
    neg = [peak(p) for p in sorted((base / "negative").glob("*.wav"))]
    return {"pos": pos, "neg": neg}


def calibrate_threshold(pos: list, neg: list) -> float:
    """Pick a decision threshold from the REAL recording scores: fire on every real
    positive and reject every real negative when they separate; otherwise favor
    recall (sit just below the quietest positive). Clamped to [0.30, 0.70]."""
    neg_max = float(max(neg)) if neg else 0.0
    pos_min = float(min(pos)) if pos else 1.0
    thr = neg_max + 0.05 if neg_max + 0.05 <= pos_min else pos_min - 0.02
    return round(min(0.70, max(0.30, thr)), 2)


def run_fit(phrase: str, *, augment: int = 80, neg_count: int = 6000,
            epochs: int = 150, settings=None) -> int:
    try:
        import numpy as np
        import onnx  # noqa: F401  (torch's legacy ONNX exporter needs it)
        import torch

        from openwakeword.utils import AudioFeatures
    except ImportError as exc:
        print(f"wake-fit needs the training stack ({exc.name}). Install it: "
              f"pip install torch onnx  (openWakeWord + numpy come with the mic extra).",
              file=sys.stderr)
        return 2

    from .settings import VoiceSettings
    from .train import _merge_conf, model_path_for, slugify
    from .wake_record import samples_dir

    torch.manual_seed(0)  # reproducible training (augmentation rng is seeded too)
    settings = settings or VoiceSettings.load()
    slug = slugify(phrase)
    pos_clips = _load_wavs(samples_dir(slug) / "positive")
    user_neg = _load_wavs(samples_dir(slug) / "negative")
    if len(pos_clips) < 5:
        print(f"need at least 5 positive recordings — found {len(pos_clips)}. "
              f"run: kow-voice wake-record {phrase}", file=sys.stderr)
        return 2
    print(f"wake-fit '{phrase}': {len(pos_clips)} positives, {len(user_neg)} user negatives.")

    rng = np.random.default_rng(0)
    af = AudioFeatures(inference_framework="onnx")

    def windows(clips_int16):
        """Embed fixed-length clips and take the first WIN-frame window of each."""
        if not clips_int16:
            return np.zeros((0, WIN, 96), dtype=np.float32)
        emb = af.embed_clips(np.stack(clips_int16).astype(np.int16), batch_size=64)
        return emb[:, :WIN, :].astype(np.float32)

    # Positives: each recording -> `augment` randomly-placed/noised buffers.
    print(f"augmenting + embedding positives (x{augment})…")
    aug = [_augment(w, user_neg, rng) for w in pos_clips for _ in range(augment)]
    pos = windows(aug)

    # Negatives = a big bank of generic real negative frames + the user's OWN
    # other-speech as HARD negatives (augmented like the positives, weighted up, so
    # the model learns the word rather than just the speaker's voice).
    print("fetching negative features…")
    cache = Path("~/.cache/kowalski/negative_features.npy").expanduser()
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.exists():
        import urllib.request
        urllib.request.urlretrieve(NEG_FEATURES_URL, cache)
    negfeat = np.load(cache, mmap_mode="r")
    starts = rng.integers(0, negfeat.shape[0] - WIN, size=neg_count)
    generic = np.stack([np.asarray(negfeat[s:s + WIN]) for s in starts]).astype(np.float32)
    if user_neg:
        print(f"augmenting + embedding user (hard) negatives (x{augment})…")
        hard = windows([_augment(n, user_neg, rng) for n in user_neg for _ in range(augment)])
    else:
        hard = np.zeros((0, WIN, 96), dtype=np.float32)

    print(f"training on {len(pos)} pos + {len(generic)} generic + {len(hard)} hard negatives…")
    X = torch.tensor(np.concatenate([pos, generic, hard]))
    y = torch.tensor([1.0] * len(pos) + [0.0] * (len(generic) + len(hard))).unsqueeze(1)
    pos_w = (len(generic) + len(hard)) / max(1, len(pos))
    w = torch.tensor([pos_w] * len(pos) + [1.0] * len(generic) + [4.0] * len(hard)).unsqueeze(1)
    perm = torch.randperm(len(X))
    X, y, w = X[perm], y[perm], w[perm]
    nval = len(X) // 5
    Xtr, ytr, wtr, Xval, yval = X[nval:], y[nval:], w[nval:], X[:nval], y[:nval]

    net = _net()
    loss_fn = torch.nn.BCELoss(reduction="none")
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    for ep in range(epochs):
        net.train()
        for i in range(0, len(Xtr), 512):
            xb, yb, wb = Xtr[i:i + 512], ytr[i:i + 512], wtr[i:i + 512]
            opt.zero_grad()
            (loss_fn(net(xb), yb) * wb).mean().backward()
            opt.step()

    # Threshold: sit just above the negatives (99th percentile) so false fires are
    # rare; then report the recall that buys.
    net.eval()
    with torch.no_grad():
        ps = net(Xval[yval.squeeze() > 0.5]).squeeze().numpy() if (yval > 0.5).any() else np.array([0.0])
        ns = net(Xval[yval.squeeze() <= 0.5]).squeeze().numpy()
    thr = float(min(0.9, max(0.3, np.percentile(ns, 99) + 0.02 if ns.size else 0.5)))
    recall = float((ps >= thr).mean())
    fp = float((ns >= thr).mean())
    print(f"  val @thr={thr:.2f}: recall = {recall*100:.0f}% · FP = {fp*100:.2f}% · "
          f"pos median = {np.median(ps):.3f} · neg median = {np.median(ns):.3f}")

    dest = model_path_for(phrase, None)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # legacy exporter (needs `onnx`, not `onnxscript`); tiny model -> single .onnx
    torch.onnx.export(net, torch.rand(1, WIN, 96), str(dest),
                      input_names=["x"], output_names=["sigmoid"], dynamo=False)

    # Real end-to-end check on the actual recordings, and a threshold derived from
    # them (trumps the augmented-window threshold above). Best-effort: a verify
    # failure must not lose a trained model, so fall back to thr.
    try:
        scored = verify_recordings(slug, dest)
        thr = calibrate_threshold(scored["pos"], scored["neg"])
        pos_fire = sum(s >= thr for s in scored["pos"])
        neg_fire = sum(s >= thr for s in scored["neg"])
        n_pos, n_neg = len(scored["pos"]), len(scored["neg"])
        print(f"  recordings @thr={thr:.2f}: {pos_fire}/{n_pos} positives fire · "
              f"{neg_fire}/{n_neg} negatives")
        if (n_pos and pos_fire / n_pos < 0.9) or (n_neg and neg_fire / n_neg > 0.15):
            print("  ! weak model — record more/clearer takes or more varied "
                  "negatives, then rerun.")
    except Exception as exc:
        print(f"  (skipped real-recording verify: {type(exc).__name__}: {exc})")

    _merge_conf({"KOW_WAKE_MODEL": str(dest), "KOW_WAKE_WORD": slug,
                 "KOW_WAKE_THRESHOLD": f"{thr:.2f}"}, None)
    print(f"registered: {dest}\n"
          f"(KOW_WAKE_MODEL set, KOW_WAKE_THRESHOLD={thr:.2f}, wake mode = both) — "
          f"try: kow-voice wake-test")
    return 0
