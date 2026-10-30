import io

import pytest
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from billchecker.ingest import MAX_BYTES, MAX_IMAGE_EDGE, IngestError, ingest, sniff_type


def by_name(files, name):
    return next(f for f in files if f.path.name == name)


def pdf_with_pages(n, text="Line of text long enough to count as a real text layer on this page."):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for _ in range(n):
        c.drawString(72, 700, text)
        c.showPage()
    c.save()
    return buf.getvalue()


def jpeg(size=(200, 100), **save_kw):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format="JPEG", **save_kw)
    return buf.getvalue()


def test_text_pdf_pages_come_back_as_text(fixture_files):
    doc = ingest(by_name(fixture_files, "clean_bill.pdf").path.read_bytes())
    assert doc.kind == "pdf"
    [page] = doc.pages
    assert page.image is None
    assert "Amount due $40.00" in page.text


def test_scanned_pdf_pages_come_back_as_images(fixture_files):
    doc = ingest(by_name(fixture_files, "denial_bill_scan.pdf").path.read_bytes())
    [page] = doc.pages
    assert page.text is None
    assert page.media_type == "image/png"
    assert max(Image.open(io.BytesIO(page.image)).size) <= MAX_IMAGE_EDGE


def test_photo_is_downscaled_jpeg(fixture_files):
    raw = by_name(fixture_files, "clean_bill_photo.jpg").path.read_bytes()
    assert max(Image.open(io.BytesIO(raw)).size) > MAX_IMAGE_EDGE
    doc = ingest(raw)
    [page] = doc.pages
    assert doc.kind == "image" and page.media_type == "image/jpeg"
    assert max(Image.open(io.BytesIO(page.image)).size) == MAX_IMAGE_EDGE


def test_png_screenshot_accepted(fixture_files):
    doc = ingest(by_name(fixture_files, "network_eob_screenshot.png").path.read_bytes())
    assert doc.pages[0].image is not None


def test_exif_rotation_applied_and_metadata_stripped():
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees
    exif[0x010F] = "PhoneMaker"
    doc = ingest(jpeg((200, 100), exif=exif))
    out = Image.open(io.BytesIO(doc.pages[0].image))
    assert out.size == (100, 200)
    assert len(out.getexif()) == 0


def test_multi_page_pdf_numbered_from_one():
    doc = ingest(pdf_with_pages(3))
    assert [p.number for p in doc.pages] == [1, 2, 3]


def test_mixed_pdf_only_renders_pages_without_text():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.drawString(72, 700, "This page has a perfectly ordinary text layer on it.")
    c.showPage()
    c.rect(72, 600, 200, 100, fill=1)  # no text: looks like a scan
    c.showPage()
    c.save()
    doc = ingest(buf.getvalue())
    assert doc.pages[0].text is not None and doc.pages[0].image is None
    assert doc.pages[1].text is None and doc.pages[1].image is not None


@pytest.mark.parametrize(
    "data, code",
    [
        (b"%PDF-" + b"0" * MAX_BYTES, "too_large"),
        (b"hello, not a document", "unsupported_type"),
        (b"\x00\x00\x00\x18ftypheic" + b"0" * 32, "unsupported_type"),
        (b"%PDF-1.4 this is not really a pdf", "unreadable"),
        (b"\x89PNG\r\n\x1a\n" + b"corrupt", "unreadable"),
    ],
)
def test_rejects_bad_uploads(data, code):
    with pytest.raises(IngestError) as err:
        ingest(data)
    assert err.value.code == code
    assert err.value.message


def test_heic_message_asks_for_jpg():
    with pytest.raises(IngestError) as err:
        ingest(b"\x00\x00\x00\x18ftypheic" + b"0" * 32)
    assert "JPG" in err.value.message


def test_rejects_too_many_pages():
    with pytest.raises(IngestError) as err:
        ingest(pdf_with_pages(21))
    assert err.value.code == "too_many_pages"


def test_sniff_type():
    assert sniff_type(b"%PDF-1.7") == "pdf"
    assert sniff_type(jpeg()) == "jpeg"
    assert sniff_type(b"GIF89a") is None
