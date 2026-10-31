"""Synthetic bills and EOBs for tests and extraction evals.

Each case is defined once as data. From that we render the document (PDF,
photo, or scan) and build the extraction we expect from it, so the two can
never drift apart. All names and numbers are fictional.
"""

import io
import random
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

import pypdfium2
from PIL import Image, ImageFilter, ImageOps
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

PROVIDER = "Riverside Medical Group"
INSURER = "Example Health Plan"
DOS = "2026-03-04"


@dataclass(frozen=True)
class Row:
    code: Optional[str]
    description: str
    charge: str
    units: int = 1
    service_date: str = DOS


@dataclass(frozen=True)
class EobRow:
    code: str
    billed: str
    allowed: str
    paid: str
    owe: str
    status: str = "processed"  # processed | denied
    reason: Optional[str] = None
    service_date: str = DOS


@dataclass(frozen=True)
class BillSpec:
    rows: List[Row]
    adjustments: str
    balance: str
    billed: Optional[str] = None  # defaults to the sum of rows
    out_of_network: bool = False
    account: str = "00098765432"


@dataclass(frozen=True)
class EobSpec:
    rows: List[EobRow]


@dataclass(frozen=True)
class Case:
    name: str
    bill: BillSpec
    eob: Optional[EobSpec]
    expected_rules: List[str]
    variants: List[str] = field(default_factory=list)  # "photo", "scan" (bill) / "screenshot" (eob)


OFFICE = Row("99213", "Office visit, established patient", "150.00")
CBC = Row("85025", "Complete blood count", "40.00")
DRAW = Row("36415", "Venipuncture", "15.00")
XRAY = Row("71046", "Chest X-ray, 2 views", "120.00")

EOB_OFFICE = EobRow("99213", "150.00", "100.00", "80.00", "20.00")
EOB_CBC = EobRow("85025", "40.00", "25.00", "10.00", "15.00")
EOB_DRAW = EobRow("36415", "15.00", "10.00", "5.00", "5.00")
CLEAN_EOB = EobSpec([EOB_OFFICE, EOB_CBC, EOB_DRAW])

CASES = [
    Case("clean", BillSpec([OFFICE, CBC, DRAW], adjustments="-165.00", balance="40.00"), CLEAN_EOB, [], ["photo"]),
    Case(
        "duplicate",
        BillSpec([OFFICE, CBC, CBC, DRAW], adjustments="-165.00", balance="80.00"),
        None,
        ["duplicate_line"],
    ),
    Case(
        "balance",
        BillSpec([OFFICE, CBC, DRAW], adjustments="-110.00", balance="95.00"),
        CLEAN_EOB,
        ["balance_mismatch"],
        ["photo"],
    ),
    Case(
        "denial",
        BillSpec([OFFICE, CBC, DRAW], adjustments="-125.00", balance="80.00"),
        EobSpec(
            [
                EOB_OFFICE,
                EobRow("85025", "40.00", "0.00", "0.00", "0.00", "denied", "Not medically necessary (CO-50)"),
                EOB_DRAW,
            ]
        ),
        ["balance_mismatch", "billed_after_denial"],
        ["scan"],
    ),
    Case(
        "network",
        BillSpec([OFFICE, CBC, DRAW], adjustments="-165.00", balance="40.00", out_of_network=True),
        CLEAN_EOB,
        ["network_mismatch"],
        ["screenshot"],
    ),
    Case("summary", BillSpec([], billed="1250.00", adjustments="-900.00", balance="350.00"), None, ["no_itemization"]),
    # The X-ray never reached the insurer, so the patient is billed for all of it.
    Case(
        "not_billed",
        BillSpec([OFFICE, CBC, DRAW, XRAY], adjustments="-165.00", balance="160.00"),
        CLEAN_EOB,
        ["balance_mismatch", "not_on_eob"],
    ),
    # The office visit is $175.00 on the bill but was billed to the insurer at $150.00.
    Case(
        "charge_diff",
        BillSpec([Row("99213", "Office visit, established patient", "175.00"), CBC, DRAW], adjustments="-190.00", balance="40.00"),
        CLEAN_EOB,
        ["charge_mismatch"],
    ),
    # The patient paid at the visit, and after insurance the account is in credit.
    Case(
        "credit",
        BillSpec([OFFICE, CBC, DRAW], adjustments="-250.00", balance="-45.00"),
        CLEAN_EOB,
        ["balance_mismatch", "credit_balance"],
    ),
    # The insurer paid, but the bill shows no payment yet.
    Case(
        "unpaid",
        BillSpec([OFFICE, CBC, DRAW], adjustments="0.00", balance="205.00"),
        CLEAN_EOB,
        ["balance_mismatch", "payment_not_applied"],
    ),
]


# --- Formatting -------------------------------------------------------------------


def us_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return "{:02d}/{:02d}/{}".format(d.month, d.day, d.year)


def usd(amount: str) -> str:
    v = Decimal(amount)
    return "{}${:,.2f}".format("-" if v < 0 else "", abs(v))


def billed_total(spec: BillSpec) -> str:
    if spec.billed is not None:
        return spec.billed
    return str(sum((Decimal(r.charge) for r in spec.rows), Decimal("0.00")))


def bill_row_text(r: Row) -> str:
    return "{} {} {} {} {}".format(us_date(r.service_date), r.code or "", r.description, r.units, usd(r.charge))


def eob_row_text(r: EobRow) -> str:
    status = "Denied: {}".format(r.reason) if r.status == "denied" else "Processed"
    return "{} {} {} {} {} {} {}".format(
        us_date(r.service_date), r.code, usd(r.billed), usd(r.allowed), usd(r.paid), usd(r.owe), status
    )


OON_NOTICE = "Notice: This provider is out of network for your health plan."
AMOUNT_DUE = "Amount due {}"
EOB_TOTAL = "Total you may owe the provider {}"


# --- Rendering --------------------------------------------------------------------

BILL_COLS = [72, 150, 200, 430, 480]
EOB_COLS = [54, 120, 170, 225, 285, 345, 425]


def _render(lines: List[tuple]) -> bytes:
    """lines: (y_step, [(x, text, bold)]) drawn top to bottom."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=1)
    y = 740
    for step, cells in lines:
        y -= step
        for x, text, bold in cells:
            c.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
            c.drawString(x, y, text)
    c.showPage()
    c.save()
    return buf.getvalue()


def render_bill(spec: BillSpec) -> bytes:
    dates = sorted(r.service_date for r in spec.rows) or [DOS]
    lines = [
        (0, [(72, PROVIDER, True)]),
        (14, [(72, "200 River Road, Springfield", False)]),
        (24, [(72, "PATIENT STATEMENT", True)]),
        (16, [(72, "Statement date: 04/01/2026", False)]),
        (14, [(72, "Account: {}".format(spec.account), False)]),
        (14, [(72, "Patient: Sam Example", False)]),
        (14, [(72, "Dates of service: {} - {}".format(us_date(dates[0]), us_date(dates[-1])), False)]),
    ]
    if spec.out_of_network:
        lines.append((20, [(72, OON_NOTICE, True)]))
    if spec.rows:
        header = ["Date", "Code", "Description", "Units", "Charge"]
        lines.append((28, [(x, h, True) for x, h in zip(BILL_COLS, header)]))
        for r in spec.rows:
            cells = [us_date(r.service_date), r.code or "", r.description, str(r.units), usd(r.charge)]
            lines.append((16, [(x, t, False) for x, t in zip(BILL_COLS, cells)]))
    else:
        lines.append((28, [(72, "Summary of charges for this visit", True)]))
    lines += [
        (28, [(72, "Total charges {}".format(usd(billed_total(spec))), False)]),
        (14, [(72, "Insurance payments and adjustments {}".format(usd(spec.adjustments)), False)]),
        (18, [(72, AMOUNT_DUE.format(usd(spec.balance)), True)]),
        (30, [(72, "Questions? Call billing at 555-0100.", False)]),
    ]
    return _render(lines)


def render_eob(spec: EobSpec) -> bytes:
    lines = [
        (0, [(54, INSURER, True)]),
        (14, [(54, "EXPLANATION OF BENEFITS - THIS IS NOT A BILL", True)]),
        (20, [(54, "Member: Sam Example", False)]),
        (14, [(54, "Claim number: C-2026-0001", False)]),
        (14, [(54, "Provider: {}".format(PROVIDER), False)]),
        (14, [(54, "Network status: In-network", False)]),
    ]
    header = ["Date", "Code", "Billed", "Allowed", "Plan paid", "You may owe", "Status"]
    lines.append((28, [(x, h, True) for x, h in zip(EOB_COLS, header)]))
    for r in spec.rows:
        status = "Denied: {}".format(r.reason) if r.status == "denied" else "Processed"
        cells = [us_date(r.service_date), r.code, usd(r.billed), usd(r.allowed), usd(r.paid), usd(r.owe), status]
        lines.append((16, [(x, t, False) for x, t in zip(EOB_COLS, cells)]))
    total = sum((Decimal(r.owe) for r in spec.rows), Decimal("0.00"))
    lines.append((28, [(54, EOB_TOTAL.format(usd(str(total))), True)]))
    return _render(lines)


def _pdf_to_image(pdf: bytes, scale: float = 2.0) -> Image.Image:
    doc = pypdfium2.PdfDocument(pdf)
    try:
        return doc[0].render(scale=scale).to_pil().convert("RGB")
    finally:
        doc.close()


def _degrade(img: Image.Image, seed: int, angle: float, blur: float) -> Image.Image:
    """Make a clean render look like a phone photo or office scan."""
    rnd = random.Random(seed)
    img = ImageOps.grayscale(img)
    img = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=200)
    img = img.filter(ImageFilter.GaussianBlur(blur))
    noise = Image.effect_noise(img.size, 18)
    img = Image.blend(img, noise, 0.12)
    # Uneven lighting: darken one side.
    w, h = img.size
    shade = Image.linear_gradient("L").rotate(90).resize((w, h))
    img = Image.composite(img, Image.new("L", (w, h), rnd.randint(90, 120)), shade.point(lambda v: 255 - v // 4))
    return img.convert("RGB")


def photo(pdf: bytes, seed: int) -> bytes:
    img = _degrade(_pdf_to_image(pdf), seed, angle=2.5, blur=0.9)
    framed = Image.new("RGB", (img.width + 160, img.height + 220), (70, 60, 50))  # table under the paper
    framed.paste(img, (80, 110))
    buf = io.BytesIO()
    framed.save(buf, format="JPEG", quality=60)
    return buf.getvalue()


def scan(pdf: bytes, seed: int) -> bytes:
    img = _degrade(_pdf_to_image(pdf, scale=1.5), seed, angle=-0.8, blur=0.5)
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=108)
    return buf.getvalue()


def screenshot(pdf: bytes) -> bytes:
    buf = io.BytesIO()
    _pdf_to_image(pdf, scale=1.5).save(buf, format="PNG")
    return buf.getvalue()


# --- Expected extraction ----------------------------------------------------------


def expected_bill(spec: BillSpec) -> Dict:
    dates = sorted(r.service_date for r in spec.rows) or [DOS]
    return {
        "schema_version": "1.0",
        "provider_name": PROVIDER,
        "account_number_redacted": "****" + spec.account[-4:],
        "statement_date": "2026-04-01",
        "dates_of_service": {"start": dates[0], "end": dates[-1]},
        "line_items": [
            {
                "line_id": "L{}".format(i),
                "service_date": r.service_date,
                "description": r.description,
                "code": r.code,
                "code_type": "CPT" if r.code else None,
                "units": r.units,
                "charge": r.charge,
                "source_page": 1,
                "source_text": bill_row_text(r),
            }
            for i, r in enumerate(spec.rows, 1)
        ],
        "totals": {
            "billed": billed_total(spec),
            "adjustments": spec.adjustments,
            "patient_balance": spec.balance,
            "source": {"page": 1, "text": AMOUNT_DUE.format(usd(spec.balance))},
        },
        "itemized": bool(spec.rows),
        "out_of_network_marker": {"page": 1, "text": OON_NOTICE} if spec.out_of_network else None,
        "extraction_confidence": "high",
    }


def expected_eob(spec: EobSpec) -> Dict:
    total = str(sum((Decimal(r.owe) for r in spec.rows), Decimal("0.00")))
    return {
        "schema_version": "1.0",
        "insurer": INSURER,
        "claim_id": "C-2026-0001",
        "service_lines": [
            {
                "line_id": "E{}".format(i),
                "service_date": r.service_date,
                "code": r.code,
                "billed": r.billed,
                "allowed": r.allowed,
                "insurer_paid": r.paid,
                "patient_responsibility": r.owe,
                "status": r.status,
                "denial_reason": r.reason,
                "network_status": "in_network",
                "source_page": 1,
                "source_text": eob_row_text(r),
            }
            for i, r in enumerate(spec.rows, 1)
        ],
        "totals": {
            "patient_responsibility": total,
            "source": {"page": 1, "text": EOB_TOTAL.format(usd(total))},
        },
    }


# --- Files ------------------------------------------------------------------------


@dataclass(frozen=True)
class FixtureFile:
    path: Path
    case: Case
    kind: str  # "bill" | "eob"
    variant: str  # "pdf" | "photo" | "scan" | "screenshot"
    expected: Dict


def build_files(out_dir: Path) -> List[FixtureFile]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []

    def write(name: str, data: bytes, case: Case, kind: str, variant: str, expected: Dict) -> None:
        path = out_dir / name
        path.write_bytes(data)
        files.append(FixtureFile(path, case, kind, variant, expected))

    for seed, case in enumerate(CASES):
        bill_pdf = render_bill(case.bill)
        exp_bill = expected_bill(case.bill)
        write("{}_bill.pdf".format(case.name), bill_pdf, case, "bill", "pdf", exp_bill)
        if "photo" in case.variants:
            write("{}_bill_photo.jpg".format(case.name), photo(bill_pdf, seed), case, "bill", "photo", exp_bill)
        if "scan" in case.variants:
            write("{}_bill_scan.pdf".format(case.name), scan(bill_pdf, seed), case, "bill", "scan", exp_bill)
        if case.eob:
            eob_pdf = render_eob(case.eob)
            exp_eob = expected_eob(case.eob)
            write("{}_eob.pdf".format(case.name), eob_pdf, case, "eob", "pdf", exp_eob)
            if "screenshot" in case.variants:
                write("{}_eob_screenshot.png".format(case.name), screenshot(eob_pdf), case, "eob", "screenshot", exp_eob)
    return files
