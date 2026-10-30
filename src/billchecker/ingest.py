"""Turn uploaded files into pages of text or images for extraction.

PDF pages with a usable text layer are sent as text (cheaper, exact).
Pages without one (scans) and photos (JPG, PNG, HEIC) are sent as images.
One upload can hold several files, e.g. a photo of each page of a bill;
they become one document with pages numbered across all files.
"""

import io
import logging
from dataclasses import dataclass
from typing import List, Optional

import pdfplumber
import pypdfium2
import pillow_heif
from PIL import Image, ImageOps

MAX_BYTES = 20 * 1024 * 1024  # per upload, across all its files
MAX_PAGES = 20  # per upload, across all its files
MAX_FILES = 10
# Pages with fewer non-space characters than this are treated as scans.
MIN_TEXT_CHARS = 40
# Long edge for images sent to the model. Larger images are downscaled by the
# API anyway, so sending more only costs upload time.
MAX_IMAGE_EDGE = 1568
PDF_RENDER_SCALE = 2.0  # 144 dpi
Image.MAX_IMAGE_PIXELS = 60_000_000
# pdfminer logs page content at DEBUG; keep document text out of logs at any app log level.
logging.getLogger("pdfminer").setLevel(logging.WARNING)
# iPhones save photos as HEIC by default.
pillow_heif.register_heif_opener()


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
    file_index: int = 0  # which uploaded file the page came from


@dataclass(frozen=True)
class Document:
    kind: str  # "pdf", "image", or "mixed"
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
    return ingest_many([data])


def ingest_many(files: List[bytes]) -> Document:
    """Several files of one document (e.g. one photo per page) -> one Document."""
    if not files:
        raise IngestError("unsupported_type", "Please choose a file to upload.")
    if len(files) > MAX_FILES:
        raise IngestError("too_many_files", "Please upload at most 10 files at a time.")
    if sum(len(f) for f in files) > MAX_BYTES:
        raise IngestError("too_large", "These files add up to more than 20 MB. Please upload smaller files.")
    pages: List[Page] = []
    kinds = set()
    for index, data in enumerate(files):
        doc = _ingest_one(data)
        kinds.add(doc.kind)
        for p in doc.pages:
            pages.append(Page(len(pages) + 1, p.text, p.image, p.media_type, index))
        if len(pages) > MAX_PAGES:
            raise IngestError("too_many_pages", "This upload has more than 20 pages. Please upload only the bill pages.")
    return Document(kind=kinds.pop() if len(kinds) == 1 else "mixed", pages=pages)


def _ingest_one(data: bytes) -> Document:
    kind = sniff_type(data)
    if kind == "pdf":
        return _ingest_pdf(data)
    if kind in ("png", "jpeg", "heic"):
        return Document(kind="image", pages=[_image_page(1, data)])
    raise IngestError("unsupported_type", "Please upload a PDF, JPG, PNG, or iPhone (HEIC) photo.")


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
