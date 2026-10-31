"""Train the in-browser photo quality model with TensorFlow/Keras, for TensorFlow.js.

Same task as scripts/train_photo_quality.py (blurry / too dark / cut off),
but this model runs in the patient's browser, so a bad photo is caught before
it is uploaded at all. Two differences from the server model's training:

- Browsers resize images with their own algorithms, so each sample uses a
  random resampling method (bilinear, bicubic, Lanczos, box, nearest).
- The browser sees the original photo, not the app's re-encoded copy, so half
  the samples skip the ingest step.

Writes (served by FastAPI under /models/photo-quality/):
    frontend/public/models/photo-quality/manifest.json   architecture, weight layout, thresholds, metrics
    frontend/public/models/photo-quality/weights.bin     float32 weights, in manifest order
    tests/data/tfjs_parity.json                          inputs + Keras outputs to check the JS model

Weights are exported directly (no tensorflowjs converter); the browser
rebuilds the same layers and loads them in order.

    .venv/bin/python scripts/train_photo_quality_tf.py           # ~15-25 minutes on CPU
    .venv/bin/python scripts/train_photo_quality_tf.py --quick
"""

import argparse
import io
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "scripts")]
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

from billchecker.ingest import _image_page  # noqa: E402
from billchecker.photo_quality import LABELS, SIZE, features  # noqa: E402
from train_photo_quality import metrics, photograph, pick_threshold, random_document  # noqa: E402

OUT_DIR = ROOT / "frontend" / "public" / "models" / "photo-quality"
PARITY_FILE = ROOT / "tests" / "data" / "tfjs_parity.json"
RESAMPLERS = [Image.BILINEAR, Image.BICUBIC, Image.LANCZOS, Image.BOX, Image.NEAREST]
FILTERS = [16, 32, 64, 96, 128]


def sample(seed: int):
    rnd = random.Random(seed)
    labels = [rnd.random() < 0.3, rnd.random() < 0.25, rnd.random() < 0.25]
    jpeg = photograph(random_document(rnd), rnd, *labels)
    if rnd.random() < 0.5:
        jpeg = _image_page(1, jpeg).image  # as the server sees it
    img = Image.open(io.BytesIO(jpeg))
    x = features(img, resample=rnd.choice(RESAMPLERS))
    return np.transpose(x, (1, 2, 0)), np.array(labels, dtype=np.float32)  # channels-last for TF


def make_dataset(seeds, workers):
    with Pool(workers) as pool:
        out = pool.map(sample, seeds, chunksize=16)
    return np.stack([x for x, _ in out]), np.stack([y for _, y in out])


def normalize(x):
    """Done outside the model, identically in the browser: (x/255 - 0.5) / 0.25."""
    return x.astype(np.float32) * (4.0 / 255.0) - 2.0


def build_model():
    import keras
    from keras import layers

    keras.utils.set_random_seed(0)
    inp = keras.Input((SIZE, SIZE, 2))
    x = inp
    for f in FILTERS:
        x = layers.Conv2D(f, 3, padding="same", use_bias=False)(x)
        x = layers.BatchNormalization()(x)
        x = layers.ReLU()(x)
        x = layers.MaxPooling2D(2)(x)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(0.2)(x)
    out = layers.Dense(len(LABELS))(x)
    return keras.Model(inp, out)


def export(model, thresholds, test_metrics, n, epochs):
    import tensorflow as tf

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    blobs, entries, offset = [], [], 0
    for layer in model.layers:
        for w, var in zip(layer.get_weights(), layer.weights):
            arr = np.ascontiguousarray(w, dtype="<f4")
            entries.append({"layer": layer.name, "name": var.path, "shape": list(arr.shape), "offset": offset})
            blobs.append(arr.tobytes())
            offset += arr.nbytes
    (OUT_DIR / "weights.bin").write_bytes(b"".join(blobs))
    manifest = {
        "version": 1,
        "labels": list(LABELS),
        "input": {"size": SIZE, "channels": ["whole page", "detail tile"], "normalize": "x * 4/255 - 2"},
        "architecture": {"filters": FILTERS, "kernel": 3, "batchnorm_epsilon": 0.001, "dense": len(LABELS)},
        "weights": entries,
        "thresholds": thresholds,
        "test_metrics": test_metrics,
        "training": {"framework": "TensorFlow {} / Keras".format(tf.__version__), "samples": n, "epochs": epochs},
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def main():
    import keras

    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    n_train, n_val, n_test, epochs = (300, 100, 100, 2) if args.quick else (4000, 800, 800, 14)

    t0 = time.time()
    xtr, ytr = make_dataset(range(3 * 10**6, 3 * 10**6 + n_train), args.workers)
    xva, yva = make_dataset(range(4 * 10**6, 4 * 10**6 + n_val), args.workers)
    xte, yte = make_dataset(range(5 * 10**6, 5 * 10**6 + n_test), args.workers)
    print("data: {} / {} / {} in {:.0f}s".format(len(xtr), len(xva), len(xte), time.time() - t0), flush=True)

    model = build_model()
    steps = epochs * ((len(xtr) + 63) // 64)
    lr = keras.optimizers.schedules.CosineDecay(1e-4, steps, warmup_target=3e-3, warmup_steps=steps // 8)
    model.compile(optimizer=keras.optimizers.AdamW(lr, weight_decay=1e-4), loss=keras.losses.BinaryCrossentropy(from_logits=True))

    def flips(x, y):
        import tensorflow as tf

        return tf.image.random_flip_left_right(x), y

    import tensorflow as tf

    train = tf.data.Dataset.from_tensor_slices((normalize(xtr), ytr)).shuffle(len(xtr), seed=0).map(flips).batch(64)
    model.fit(train, validation_data=(normalize(xva), yva), epochs=epochs, verbose=2)

    sig = lambda z: 1 / (1 + np.exp(-z))  # noqa: E731
    pv = sig(model.predict(normalize(xva), verbose=0))
    thresholds = {label: pick_threshold(pv[:, i], yva[:, i]) for i, label in enumerate(LABELS)}
    pt = sig(model.predict(normalize(xte), verbose=0))
    test = metrics(pt, yte, thresholds)
    print("thresholds:", thresholds)
    print("test:", json.dumps(test, indent=1), flush=True)
    export(model, thresholds, test, len(xtr), epochs)

    # Fixed inputs and the Keras outputs for them, so a test can prove the JS model computes the same thing.
    PARITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    picks = xte[:4]
    PARITY_FILE.write_text(json.dumps({
        "inputs": [p.astype(int).flatten().tolist() for p in picks],
        "logits": model.predict(normalize(picks), verbose=0).round(5).tolist(),
    }))
    size = (OUT_DIR / "weights.bin").stat().st_size
    print("wrote {} ({} KB) and {}".format(OUT_DIR, size // 1024, PARITY_FILE.name))


if __name__ == "__main__":
    main()
