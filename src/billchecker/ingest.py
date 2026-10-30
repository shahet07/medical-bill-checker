"""Turn an uploaded file into pages of text or images for extraction.

PDF pages with a usable text layer are sent as text (cheaper, exact).
Pages without one (scans) and photos are sent as images.
"""

import io
from dataclasses import dataclass
from typing import List, Optional

import pdfplumber
import pypdfium2
from PIL import Image, ImageOps

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 20
# Pages with fewer non-space characters than this are treated as scans.
MIN_TEXT_CHARS = 40
# Long edge for images sent to the model. Larger images are downscaled by the
# API anyway, so sending more only costs upload time.
MAX_IMAGE_EDGE = 1568
PDF_RENDER_SCALE = 2.0  # 144 dpi
Image.MAX_IMAGE_PIXELS = 60_000_000


class IngestError(Exception):
    """User-facing failure. `code` is stable; `message` can be shown as is."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Page:
    number: int  # 1-based
    text: Optional[str]  # set when the page has a usable text layer
    image: Optional[bytes]  # set otherwise
    media_type: Optional[str]  # "image/png" or "image/jpeg" when image is set


@dataclass(frozen=True)
class Document:
    kind: str  # "pdf" or "image"
    pages: List[Page]

    @property
    def page_texts(self) -> List[Optional[str]]:
        return [p.text for p in self.pages]


def sniff_type(data: bytes) -> Optional[str]:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc"):
        return "heic"
    return None


def ingest(data: bytes) -> Document:
    if len(data) > MAX_BYTES:
        raise IngestError("too_large", "This file is larger than 20 MB. Please upload a smaller file.")
    kind = sniff_type(data)
    if kind == "pdf":
        return _ingest_pdf(data)
    if kind in ("png", "jpeg"):
        return Document(kind="image", pages=[_image_page(1, data)])
    if kind == "heic":
        raise IngestError("unsupported_type", "HEIC photos are not supported yet. Please upload a JPG or PNG.")
    raise IngestError("unsupported_type", "Please upload a PDF, JPG, or PNG file.")


def _ingest_pdf(data: bytes) -> Document:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) == 0:
                raise IngestError("unreadable", "This PDF has no pages.")
            if len(pdf.pages) > MAX_PAGES:
                raise IngestError("too_many_pages", "This PDF has more than 20 pages. Please upload only the bill pages.")
            texts = [p.extract_text() or "" for p in pdf.pages]
    except IngestError:
        raise
    except Exception as exc:  # pdfminer raises a variety of types for broken/encrypted files
        raise IngestError("unreadable", "This PDF could not be read. It may be damaged or password protected.") from exc

    pages = []
    scanned = [i for i, t in enumerate(texts) if _visible_chars(t) < MIN_TEXT_CHARS]
    rendered = _render_pdf_pages(data, scanned) if scanned else {}
    for i, text in enumerate(texts):
        if i in rendered:
            pages.append(Page(number=i + 1, text=None, image=rendered[i], media_type="image/png"))
        else:
            pages.append(Page(number=i + 1, text=text, image=None, media_type=None))
    return Document(kind="pdf", pages=pages)


def _visible_chars(text: str) -> int:
    return sum(1 for c in text if not c.isspace())


def _render_pdf_pages(data: bytes, indexes: List[int]) -> dict:
    out = {}
    pdf = pypdfium2.PdfDocument(data)
    try:
        for i in indexes:
            img = pdf[i].render(scale=PDF_RENDER_SCALE).to_pil()
            out[i] = _encode(_fit(img.convert("RGB")), "PNG")
    finally:
        pdf.close()
    return out


def _image_page(number: int, data: bytes) -> Page:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Image.DecompressionBombError as exc:
        raise IngestError("too_large", "This image is too large. Please upload a smaller photo.") from exc
    except Exception as exc:
        raise IngestError("unreadable", "This image could not be read. Please re-upload a clearer photo.") from exc
    # Phone photos are often stored sideways with an EXIF rotation tag.
    img = ImageOps.exif_transpose(img).convert("RGB")
    return Page(number=number, text=None, image=_encode(_fit(img), "JPEG"), media_type="image/jpeg")


def _fit(img: Image.Image) -> Image.Image:
    if max(img.size) <= MAX_IMAGE_EDGE:
        return img
    img = img.copy()
    img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.LANCZOS)
    return img


def _encode(img: Image.Image, fmt: str) -> bytes:
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.save(buf, format="JPEG", quality=90)
    else:
        img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
