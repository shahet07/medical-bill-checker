import io

import numpy as np
import pytest
from PIL import Image, ImageEnhance, ImageFilter

from billchecker.ingest import ingest
from billchecker.photo_quality import LABELS, SIZE, PhotoQuality, check_pages, features
from synthetic import CASES, photo, render_bill

PQ = PhotoQuality()
pytestmark = pytest.mark.skipif(not PQ.available, reason="photo quality model not trained (scripts/train_photo_quality.py)")


def page_image(jpeg: bytes) -> Image.Image:
    """The image as the app would see it after ingest."""
    return Image.open(io.BytesIO(ingest(jpeg).pages[0].image))


def jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@pytest.fixture(scope="module")
def good():
    return Image.open(io.BytesIO(photo(render_bill(CASES[0].bill), 3)))


def issues(img: Image.Image):
    [result] = PQ.check([page_image(jpeg(img))])
    return result["issues"]


def test_features_shape_and_determinism(good):
    f = features(good)
    assert f.shape == (2, SIZE, SIZE) and f.dtype == np.uint8
    assert np.array_equal(f, features(good))


def test_good_photo_passes(good):
    assert issues(good) == []


def test_blurry_photo_flagged(good):
    assert "blurry" in issues(good.filter(ImageFilter.GaussianBlur(max(good.size) * 0.008)))


def test_dark_photo_flagged(good):
    assert "too_dark" in issues(ImageEnhance.Brightness(good).enhance(0.08))


def test_cut_off_photo_flagged(good):
    w, h = good.size
    assert "cut_off" in issues(good.crop((0, int(h * 0.45), w, h)))


def test_scores_are_probabilities(good):
    [scores] = PQ.scores([page_image(jpeg(good))])
    assert set(scores) == set(LABELS) and all(0 <= v <= 1 for v in scores.values())


def test_text_pdf_pages_are_not_checked():
    assert check_pages(ingest(render_bill(CASES[0].bill)).pages) == []


def test_scanned_pages_are_checked(fixture_files):
    scan = next(f for f in fixture_files if f.variant == "scan")
    [result] = check_pages(ingest(scan.path.read_bytes()).pages)
    assert result["page"] == 1 and set(result["scores"]) == set(LABELS)


def test_missing_model_skips_the_check(tmp_path, good):
    missing = PhotoQuality(tmp_path / "none.onnx", tmp_path / "none.json")
    assert missing.available is False and missing.check([good]) == []


def test_upload_reports_quality(client, good):  # noqa: F811
    blurred = jpeg(good.filter(ImageFilter.GaussianBlur(max(good.size) * 0.008)))
    r = client.post("/api/uploads", data={"kind": "bill"}, files={"file": ("p.jpg", blurred, "image/jpeg")})
    assert r.status_code == 201
    [q] = r.json()["quality"]
    assert "blurry" in q["issues"]
    ok = client.post("/api/uploads", data={"kind": "bill"}, files={"file": ("p.jpg", jpeg(good), "image/jpeg")})
    assert ok.json()["quality"][0]["issues"] == []


from test_api import client, clock, llm  # noqa: E402,F401  (fixtures for test_upload_reports_quality)
