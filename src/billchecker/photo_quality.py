"""Photo quality check: is a bill photo blurry, too dark, or cut off?

A small convolutional network (trained with PyTorch by
scripts/train_photo_quality.py on synthetic bill photos, exported to ONNX)
runs on each photographed or scanned page right after upload, before any LLM
call, so the patient can retake a bad photo in seconds instead of waiting for
an "unreadable" result. It only warns; it never blocks.

Inference uses ONNX Runtime, not PyTorch, so the server stays light. If the
model or runtime is missing, the check is skipped.

The same preprocessing (`features`) is used in training and here, on the
same images the LLM would see (after ingest's resize and re-encode).
"""

import io
import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image, ImageOps

log = logging.getLogger("billchecker.photo_quality")

MODEL_DIR = Path(__file__).parent / "ml"
MODEL_FILE = MODEL_DIR / "photo_quality.onnx"
META_FILE = MODEL_DIR / "photo_quality.json"
LABELS = ("blurry", "too_dark", "cut_off")
SIZE = 192
DETAIL_EDGE = 1024  # scale at which the close-up tile is taken
TILE_STRIDE = 96


def _letterbox(img: Image.Image, size: int, resample=Image.BILINEAR) -> Image.Image:
    img = img.copy()
    img.thumbnail((size, size), resample)
    canvas = Image.new("L", (size, size), 0)
    canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2))
    return canvas


def _detail_tile(img: Image.Image, resample=Image.BILINEAR) -> Image.Image:
    """The SIZE x SIZE tile with the most contrast (usually text), at a fixed scale,
    so blur shows up whatever the photo's size or where the text is."""
    scaled = img.copy()
    scaled.thumbnail((DETAIL_EDGE, DETAIL_EDGE), resample)
    if scaled.width < SIZE or scaled.height < SIZE:
        return _letterbox(scaled, SIZE, resample)
    a = np.asarray(scaled, dtype=np.float32)
    best, best_xy = -1.0, (0, 0)
    for y in range(0, a.shape[0] - SIZE + 1, TILE_STRIDE):
        for x in range(0, a.shape[1] - SIZE + 1, TILE_STRIDE):
            s = float(a[y : y + SIZE, x : x + SIZE].std())
            if s > best:
                best, best_xy = s, (x, y)
    x, y = best_xy
    return scaled.crop((x, y, x + SIZE, y + SIZE))


def features(image: Image.Image, resample=Image.BILINEAR) -> np.ndarray:
    """uint8 array (2, SIZE, SIZE): channel 0 the whole page, channel 1 the detail tile.
    `resample` varies only in training, so models tolerate other resizers (e.g. a browser canvas)."""
    gray = ImageOps.exif_transpose(image).convert("L")
    return np.stack([np.asarray(_letterbox(gray, SIZE, resample)), np.asarray(_detail_tile(gray, resample))]).astype(np.uint8)


class PhotoQuality:
    """Lazy, thread-safe ONNX Runtime session. `available` is False if the model can't load."""

    def __init__(self, model_file: Path = MODEL_FILE, meta_file: Path = META_FILE):
        self.model_file, self.meta_file = model_file, meta_file
        self._session = None
        self._meta: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()
        self._failed = False

    def _load(self) -> bool:
        if self._session is not None or self._failed:
            return self._session is not None
        with self._lock:
            if self._session is None and not self._failed:
                try:
                    import onnxruntime as ort

                    self._meta = json.loads(self.meta_file.read_text())
                    self._session = ort.InferenceSession(str(self.model_file), providers=["CPUExecutionProvider"])
                except Exception as exc:  # missing file or runtime: skip the check
                    log.warning("photo quality model unavailable (%s)", type(exc).__name__)
                    self._failed = True
        return self._session is not None

    @property
    def available(self) -> bool:
        return self._load()

    @property
    def thresholds(self) -> Dict[str, float]:
        self._load()
        return dict((self._meta or {}).get("thresholds", {}))

    def scores(self, images: List[Image.Image]) -> List[Dict[str, float]]:
        if not images or not self._load():
            return []
        batch = np.stack([features(i) for i in images]).astype(np.float32)
        logits = self._session.run(None, {"image": batch})[0]
        probs = 1.0 / (1.0 + np.exp(-logits))
        return [{label: float(round(p[i], 4)) for i, label in enumerate(LABELS)} for p in probs]

    def check(self, images: List[Image.Image]) -> List[Dict[str, Any]]:
        th = self.thresholds
        out = []
        for scores in self.scores(images):
            issues = [label for label in LABELS if scores[label] >= th.get(label, 0.5)]
            out.append({"issues": issues, "scores": scores})
        return out


_default = PhotoQuality()


def check_pages(pages) -> List[Dict[str, Any]]:
    """Check every image page of an ingested Document (photos and scans; text pages are skipped)."""
    images, numbers = [], []
    for p in pages:
        if p.image is not None:
            images.append(Image.open(io.BytesIO(p.image)))
            numbers.append(p.number)
    results = _default.check(images)
    return [dict(r, page=n) for r, n in zip(results, numbers)]
