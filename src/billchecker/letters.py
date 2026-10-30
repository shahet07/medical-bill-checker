"""Letters a patient can send to the provider's billing office.

Letters are filled from templates using validated bill/EOB data and flags
from the rules engine. No LLM is involved, so a letter can only contain
amounts and facts that are in the extracted data. The only free text is the
patient's own optional note, included as written.

Wording is deliberately neutral: it asks the provider to review, confirm,
or explain, and never asserts that a charge is wrong or that the patient
does not owe it.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from .models import Bill, Eob, EobLine, Flag, LineItem

MAX_NOTE_CHARS = 1000

ITEMIZED_FIELDS = [
    "the date of each service",
    "the CPT, HCPCS, or revenue code for each service",
    "a description of each service",
    "the number of units",
    "the charge for each service",
    "all payments and adjustments applied, including insurance payments",
]


@dataclass(frozen=True)
class Patient:
    name: str
    address_lines: List[str]
    phone: Optional[str] = None
    email: Optional[str] = None
    # Full account number typed by the patient for the letter. We only keep the
    # last 4 characters of the extracted one, which a billing office can't look up.
    account_number: Optional[str] = None


@dataclass(frozen=True)
class Letter:
    kind: str  # "itemized_request" | "dispute"
    subject: str
    text: str


def long_date(d: date) -> str:
    return "{} {}, {}".format(d.strftime("%B"), d.day, d.year)


def usd(amount: Decimal) -> str:
    return "{}${:,.2f}".format("-" if amount < 0 else "", abs(amount))


# --- Public API -------------------------------------------------------------------


def itemized_request(bill: Bill, patient: Patient, today: date, note: Optional[str] = None) -> Letter:
    subject = "Request for an itemized bill"
    body = [
        "I am writing to request an itemized bill for the account above. "
        "Please send a statement that lists each service separately, including:",
        "\n".join("- " + f for f in ITEMIZED_FIELDS),
        "Please also confirm whether this bill was submitted to my health insurance, "
        "and place the account on hold while this request is pending.",
    ]
    return _letter("itemized_request", subject, bill, None, patient, today, body, note)


def dispute(
    bill: Bill, eob: Optional[Eob], flags: List[Flag], patient: Patient, today: date, note: Optional[str] = None
) -> Letter:
    if not flags:
        raise ValueError("a dispute letter needs at least one flag")
    lines = {li.line_id: li for li in bill.line_items}
    eob_lines = {sl.line_id: sl for sl in eob.service_lines} if eob else {}

    reviewed = "my bill" + (" dated " + long_date(bill.statement_date) if bill.statement_date else "")
    if eob:
        reviewed += " and the Explanation of Benefits (EOB) from " + (eob.insurer or "my health insurer")
    items = [
        "{}. {}".format(i, _flag_paragraph(f, bill, eob, lines, eob_lines)) for i, f in enumerate(flags, 1)
    ]
    body = [
        "I have reviewed {}. I would like you to review the following:".format(reviewed),
        "\n\n".join(items),
        "Please review these items and send me a corrected bill, or a written explanation of why the "
        "charges are correct. If you have not already sent one, please also send an itemized bill. "
        "Please place the account on hold while this review is in progress.",
    ]
    return _letter("dispute", "Request for review of charges", bill, eob, patient, today, body, note)


# --- Flag paragraphs --------------------------------------------------------------


def _service(line: LineItem) -> str:
    code = " ({})".format(line.code) if line.code else ""
    when = " on " + long_date(line.service_date) if line.service_date else ""
    return "{}{}{}, {}".format(line.description, code, when, usd(line.charge))


def _refs(flag: Flag, source: str) -> List[str]:
    return [e.ref for e in flag.evidence if e.source == source]


def _lookup(table: Dict, ref: str, flag: Flag):
    if ref not in table:
        raise ValueError("flag {} refers to {} which is not in this bill/EOB".format(flag.flag_id, ref))
    return table[ref]


def _flag_paragraph(flag: Flag, bill: Bill, eob: Optional[Eob], lines: Dict, eob_lines: Dict) -> str:
    if flag.rule == "duplicate_line":
        services = [_service(_lookup(lines, r, flag)) for r in _refs(flag, "bill")]
        return (
            "Possible duplicate charge. These lines show the same service, date, and charge:\n"
            + "\n".join("   - " + s for s in services)
            + "\n   Please confirm whether this service was provided more than once."
        )

    if flag.rule == "balance_mismatch":
        if eob is None:
            raise ValueError("balance_mismatch flag without an EOB")
        billed, owed = bill.totals.patient_balance, eob.totals.patient_responsibility
        claim = " for claim {}".format(eob.claim_id) if eob.claim_id else ""
        text = (
            "Amount due does not match my insurer's EOB. This bill shows an amount due of {}. "
            "The EOB{} shows my responsibility as {}, a difference of {}. "
            "Please reconcile the balance with the claim as processed by my insurer.".format(
                usd(billed), claim, usd(owed), usd(abs(billed - owed))
            )
        )
        if flag.confidence != "high":
            text += " If the amount due includes other services or an earlier balance, please list them."
        return text

    if flag.rule == "billed_after_denial":
        [line] = [_lookup(lines, r, flag) for r in _refs(flag, "bill")]
        matched: List[EobLine] = [_lookup(eob_lines, r, flag) for r in _refs(flag, "eob")]
        denied = all(m.status == "denied" for m in matched)
        reasons = sorted({m.denial_reason for m in matched if m.denial_reason})
        text = "Charge for a service my insurer {}: {}. My EOB shows this service as {}".format(
            "denied" if denied else "did not process",
            _service(line),
            "denied" if denied else "not processed",
        )
        text += " (reason given: {}).".format("; ".join(reasons)) if reasons else "."
        return text + (
            " Please confirm whether I am responsible for this charge, and whether the claim "
            "can be corrected and resubmitted to my insurer."
        )

    if flag.rule == "network_mismatch":
        marker = bill.out_of_network_marker
        return (
            'Network status. The bill states: "{}" My EOB shows these services were processed as '
            "in network. Please confirm the network status and, if the services were in network, "
            "adjust the bill to match.".format(marker.text if marker else "out of network")
        )

    if flag.rule == "no_itemization":
        return "The bill shows only a total. Please send an itemized bill listing each service, code, and charge."

    raise ValueError("no letter template for rule {!r}".format(flag.rule))


# --- Layout -----------------------------------------------------------------------


def _letter(
    kind: str,
    subject: str,
    bill: Bill,
    eob: Optional[Eob],
    patient: Patient,
    today: date,
    body: List[str],
    note: Optional[str],
) -> Letter:
    if not patient.name.strip():
        raise ValueError("patient name is required")
    note = (note or "").strip()
    if len(note) > MAX_NOTE_CHARS:
        raise ValueError("note is longer than {} characters".format(MAX_NOTE_CHARS))

    sender = [patient.name] + [a for a in patient.address_lines if a.strip()]
    recipient = [bill.provider_name or "Billing Office", "Attn: Billing Department"]

    ref = ["Re: " + subject]
    if patient.account_number and patient.account_number.strip():
        ref.append("Account number: " + patient.account_number.strip())
    elif bill.account_number_redacted:
        ref.append("Account number ending in " + bill.account_number_redacted.lstrip("*"))
    if bill.statement_date:
        ref.append("Statement date: " + long_date(bill.statement_date))
    dos = bill.dates_of_service
    if dos.start and dos.end and dos.start != dos.end:
        ref.append("Dates of service: {} to {}".format(long_date(dos.start), long_date(dos.end)))
    elif dos.start or dos.end:
        ref.append("Date of service: " + long_date(dos.start or dos.end))
    if eob and eob.claim_id:
        ref.append("Insurance claim number: " + eob.claim_id)

    contact = [c for c in (patient.phone, patient.email) if c]
    closing = "Thank you for your help."
    if contact:
        closing += " You can reach me at {}.".format(" or ".join(contact))

    blocks = [
        "\n".join(sender),
        long_date(today),
        "\n".join(recipient),
        "\n".join(ref),
        "Dear Billing Department,",
        *body,
    ]
    if note:
        blocks.append(note)
    blocks += [closing, "Sincerely,\n" + patient.name]
    return Letter(kind=kind, subject=subject, text="\n\n".join(blocks) + "\n")
