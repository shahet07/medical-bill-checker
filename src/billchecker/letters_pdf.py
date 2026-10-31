"""Render a Letter as a printable PDF (US Letter, standard business layout)."""

import io
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import letter as LETTER_SIZE
from reportlab.lib.styles import ParagraphStyle
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .letters import Letter

BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=11, leading=15)
ITEM = ParagraphStyle("item", parent=BODY, leftIndent=18, firstLineIndent=-18)
SUB = ParagraphStyle("sub", parent=BODY, leftIndent=36)


def _para(block: str) -> Paragraph:
    # Escape first: reportlab Paragraph text is markup, and bill text must never be interpreted as tags.
    lines = [escape(line) for line in block.split("\n")]
    style = ITEM if block[:3].rstrip(".").isdigit() and ". " in block[:4] else BODY
    return Paragraph("<br/>".join(lines).replace("   - ", "&nbsp;&nbsp;&nbsp;- "), style)


def _qr(url: str, size: float = 1.1 * inch) -> Drawing:
    widget = QrCodeWidget(url)
    x0, y0, x1, y1 = widget.getBounds()
    drawing = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    drawing.add(widget)
    return drawing


def render_pdf(letter: Letter) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER_SIZE,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
        title=letter.subject,
        author="",
        creator="",
        producer="",
        invariant=1,
    )
    story = []
    for block in letter.text.strip().split("\n\n"):
        story += [_para(block), Spacer(1, 11)]
        if letter.verify_url and letter.verify_url in block:
            story += [_qr(letter.verify_url), Spacer(1, 11)]
    doc.build(story)
    return buf.getvalue()
