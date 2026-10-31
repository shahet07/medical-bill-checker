"""Train the photo quality model (PyTorch) and export it to ONNX.

Generates labeled synthetic phone photos of bills, EOBs, and letters, with
blur, low light, and cut-off pages mixed in, passes each through the app's
real ingest step (so training sees exactly what production sees), trains a
small CNN with one output per problem, picks thresholds that keep false
"retake your photo" warnings rare, and writes:

    src/billchecker/ml/photo_quality.onnx
    src/billchecker/ml/photo_quality.json   (labels, thresholds, metrics)

    .venv/bin/python scripts/train_photo_quality.py            # ~5 minutes on a laptop
    .venv/bin/python scripts/train_photo_quality.py --quick    # smoke run
"""

import argparse
import io
import json
import random
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from billchecker.ingest import _image_page  # noqa: E402
from billchecker.photo_quality import LABELS, MODEL_DIR, SIZE, features  # noqa: E402

CODES = [("99213", "Office visit, established patient"), ("99214", "Office visit, detailed"), ("85025", "Complete blood count"),
         ("36415", "Venipuncture"), ("80053", "Comprehensive metabolic panel"), ("71046", "Chest X-ray, 2 views"),
         ("93000", "Electrocardiogram"), ("J1100", "Dexamethasone injection"), ("81001", "Urinalysis"), ("97110", "Therapeutic exercise")]


# --- Documents ------------------------------------------------------------------------------


def random_document(rnd: random.Random) -> Image.Image:
    import pypdfium2
    from synthetic import BillSpec, EobRow, EobSpec, Row, render_bill, render_eob

    kind = rnd.choice(["bill", "bill", "eob", "letter"])
    rows = [Row(c, d, "{:.2f}".format(rnd.uniform(10, 900))) for c, d in rnd.sample(CODES, rnd.randint(1, 8))]
    if kind == "bill":
        pdf = render_bill(BillSpec(rows, adjustments="-{:.2f}".format(rnd.uniform(0, 300)), balance="{:.2f}".format(rnd.uniform(0, 500))))
    elif kind == "eob":
        pdf = render_eob(EobSpec([EobRow(r.code, r.charge, "50.00", "30.00", "20.00") for r in rows]))
    else:
        from billchecker.letters import Patient, financial_assistance
        from billchecker.letters_pdf import render_pdf
        from billchecker.models import Bill
        from synthetic import expected_bill

        bill = Bill.model_validate(expected_bill(BillSpec(rows, adjustments="-10.00", balance="20.00")))
        pdf = render_pdf(financial_assistance(bill, Patient("Sam Example", ["12 Elm Street"]), date(2026, 4, 15)))
    doc = pypdfium2.PdfDocument(pdf)
    try:
        return doc[0].render(scale=rnd.uniform(1.6, 2.6)).to_pil().convert("RGB")
    finally:
        doc.close()


# --- Photo simulation -------------------------------------------------------------------------


def motion_blur(img: Image.Image, length: int, horizontal: bool) -> Image.Image:
    a = np.asarray(img, dtype=np.float32)
    out = np.zeros_like(a)
    for k in range(length):
        out += np.roll(a, k - length // 2, axis=1 if horizontal else 0)
    return Image.fromarray(np.clip(out / length, 0, 255).astype(np.uint8))


def photograph(page: Image.Image, rnd: random.Random, blurry: bool, dark: bool, cut: bool) -> bytes:
    w, h = page.size
    cut_side = rnd.choice("tblr") if cut else None
    if cut:
        keep = rnd.uniform(0.4, 0.7)
        page = {
            "t": lambda: page.crop((0, int(h * (1 - keep)), w, h)),
            "b": lambda: page.crop((0, 0, w, int(h * keep))),
            "l": lambda: page.crop((int(w * (1 - keep)), 0, w, h)),
            "r": lambda: page.crop((0, 0, int(w * keep), h)),
        }[cut_side]()
    page = page.rotate(rnd.uniform(-4, 4), resample=Image.BICUBIC, expand=True, fillcolor=(235, 235, 235))
    w, h = page.size

    # Background (table, desk) with margins; no margin on the side that's cut off.
    margins = {s: int(rnd.uniform(0.01, 0.14) * (w if s in "lr" else h)) for s in "tblr"}
    if cut_side:
        margins[cut_side] = 0
    bg_color = tuple(rnd.randint(30, 200) for _ in range(3))
    frame = Image.new("RGB", (w + margins["l"] + margins["r"], h + margins["t"] + margins["b"]), bg_color)
    frame.paste(page, (margins["l"], margins["t"]))

    # Uneven lighting and sensor noise.
    gx = np.linspace(rnd.uniform(0.75, 1.0), rnd.uniform(0.9, 1.05), frame.width, dtype=np.float32)
    gy = np.linspace(rnd.uniform(0.8, 1.0), rnd.uniform(0.9, 1.05), frame.height, dtype=np.float32)
    a = np.asarray(frame, dtype=np.float32) * np.outer(gy, gx)[..., None]
    a += np.random.default_rng(rnd.randint(0, 2**31)).normal(0, rnd.uniform(1.5, 8), a.shape).astype(np.float32)
    frame = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    long_edge = rnd.randint(1200, 3200)
    frame.thumbnail((long_edge, long_edge), Image.LANCZOS)
    L = max(frame.size)

    if blurry:
        if rnd.random() < 0.6:
            frame = frame.filter(ImageFilter.GaussianBlur(L * rnd.uniform(0.0028, 0.01)))
        else:
            frame = motion_blur(frame, max(3, int(L * rnd.uniform(0.006, 0.02))), rnd.random() < 0.5)
    elif rnd.random() < 0.3:
        frame = frame.filter(ImageFilter.GaussianBlur(L * rnd.uniform(0.0, 0.0007)))  # soft but readable: still fine

    if dark:
        frame = ImageEnhance.Brightness(frame).enhance(rnd.uniform(0.05, 0.2))
    else:
        frame = ImageEnhance.Brightness(frame).enhance(rnd.uniform(0.55, 1.15))  # dim but readable is fine

    buf = io.BytesIO()
    frame.save(buf, format="JPEG", quality=rnd.randint(55, 95))
    return buf.getvalue()


def sample(seed: int):
    rnd = random.Random(seed)
    labels = [rnd.random() < 0.3, rnd.random() < 0.25, rnd.random() < 0.25]  # blurry, too_dark, cut_off
    jpeg = photograph(random_document(rnd), rnd, *labels)
    page = _image_page(1, jpeg)  # the app's real ingest: EXIF, resize to 1568, re-encode
    return features(Image.open(io.BytesIO(page.image))), np.array(labels, dtype=np.float32)


def make_dataset(seeds, workers: int):
    with Pool(workers) as pool:
        out = pool.map(sample, seeds, chunksize=16)
    return np.stack([x for x, _ in out]), np.stack([y for _, y in out])


# --- Model --------------------------------------------------------------------------------------


def build_model():
    import torch
    from torch import nn

    def block(cin, cout):
        return nn.Sequential(nn.Conv2d(cin, cout, 3, padding=1, bias=False), nn.BatchNorm2d(cout), nn.ReLU(inplace=True), nn.MaxPool2d(2))

    class PhotoQualityNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.body = nn.Sequential(block(2, 16), block(16, 32), block(32, 64), block(64, 96), block(96, 128))
            self.head = nn.Sequential(nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Dropout(0.2), nn.Linear(128, len(LABELS)))

        def forward(self, x):  # x: raw 0-255 pixels, shape (N, 2, SIZE, SIZE)
            return self.head(self.body((x / 255.0 - 0.5) / 0.25))

    torch.manual_seed(0)
    return PhotoQualityNet()


def predict(model, x, device, batch=256):
    import torch

    model.eval()
    outs = []
    with torch.no_grad():
        for i in range(0, len(x), batch):
            outs.append(torch.sigmoid(model(torch.from_numpy(x[i : i + batch]).float().to(device))).cpu().numpy())
    return np.concatenate(outs)


def pick_threshold(probs, truth, min_precision=0.97):
    """Lowest threshold whose precision stays above min_precision: few false warnings, best recall."""
    for t in np.arange(0.2, 0.96, 0.01):
        pred = probs >= t
        if pred.sum() and (pred & (truth == 1)).sum() / pred.sum() >= min_precision:
            return float(round(t, 2))
    return 0.9


def metrics(probs, truth, thresholds):
    out = {}
    for i, label in enumerate(LABELS):
        pred, t = probs[:, i] >= thresholds[label], truth[:, i] == 1
        tp, fp, fn = int((pred & t).sum()), int((pred & ~t).sum()), int((~pred & t).sum())
        out[label] = {"precision": round(tp / max(tp + fp, 1), 3), "recall": round(tp / max(tp + fn, 1), 3), "positives": int(t.sum())}
    clean = truth.sum(axis=1) == 0
    warned = np.stack([probs[:, i] >= thresholds[l] for i, l in enumerate(LABELS)], axis=1).any(axis=1)
    out["false_warning_rate_on_good_photos"] = round(float(warned[clean].mean()), 3)
    return out


def main():
    import torch
    from torch import nn

    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    n_train, n_val, n_test, epochs = (300, 100, 100, 2) if args.quick else (4000, 800, 800, 14)

    t0 = time.time()
    xtr, ytr = make_dataset(range(0, n_train), args.workers)
    xva, yva = make_dataset(range(10**6, 10**6 + n_val), args.workers)
    xte, yte = make_dataset(range(2 * 10**6, 2 * 10**6 + n_test), args.workers)
    print("data: {} train / {} val / {} test in {:.0f}s".format(len(xtr), len(xva), len(xte), time.time() - t0))

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = build_model().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=3e-3, total_steps=epochs * ((len(xtr) + 63) // 64))
    loss_fn = nn.BCEWithLogitsLoss()
    xt, yt = torch.from_numpy(xtr), torch.from_numpy(ytr)
    for epoch in range(epochs):
        model.train()
        perm = torch.randperm(len(xt))
        total = 0.0
        for i in range(0, len(xt), 64):
            idx = perm[i : i + 64]
            xb, yb = xt[idx].float().to(device), yt[idx].to(device)
            if torch.rand(1).item() < 0.5:
                xb = torch.flip(xb, dims=[3])  # mirror: quality doesn't depend on reading direction
            opt.zero_grad()
            loss = loss_fn(model(xb), yb)
            loss.backward()
            opt.step()
            sched.step()
            total += loss.item() * len(idx)
        val_loss = loss_fn(torch.from_numpy(predict(model, xva, device)).logit(eps=1e-6), torch.from_numpy(yva)).item()
        print("epoch {:2d}  train loss {:.4f}  val loss {:.4f}".format(epoch + 1, total / len(xt), val_loss))

    pv = predict(model, xva, device)
    thresholds = {label: pick_threshold(pv[:, i], yva[:, i]) for i, label in enumerate(LABELS)}
    test = metrics(predict(model, xte, device), yte, thresholds)
    print("thresholds:", thresholds)
    print("test:", json.dumps(test, indent=1))

    MODEL_DIR.mkdir(exist_ok=True)
    model = model.to("cpu").eval()
    torch.onnx.export(
        model, torch.zeros(1, 2, SIZE, SIZE), str(MODEL_DIR / "photo_quality.onnx"),
        input_names=["image"], output_names=["logits"], dynamic_axes={"image": {0: "n"}, "logits": {0: "n"}},
        opset_version=17, dynamo=False,
    )
    meta = {
        "version": 1,
        "labels": list(LABELS),
        "input": {"name": "image", "shape": [None, 2, SIZE, SIZE], "pixels": "uint8 values as float32 (0-255)"},
        "thresholds": thresholds,
        "test_metrics": test,
        "training": {"train": len(xtr), "val": len(xva), "test": len(xte), "epochs": epochs, "framework": "PyTorch " + torch.__version__,
                     "data": "synthetic photos of bills, EOBs, and letters (scripts/train_photo_quality.py)"},
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    (MODEL_DIR / "photo_quality.json").write_text(json.dumps(meta, indent=1))
    print("wrote", MODEL_DIR / "photo_quality.onnx", "({} KB)".format((MODEL_DIR / "photo_quality.onnx").stat().st_size // 1024))


if __name__ == "__main__":
    main()
