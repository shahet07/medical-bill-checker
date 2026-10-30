import re
from datetime import date
from decimal import Decimal

import pytest

from billchecker.letters import MAX_NOTE_CHARS, Patient, dispute, itemized_request
from billchecker.models import Bill, Eob
from billchecker.rules import run_rules
from synthetic import CASES, expected_bill, expected_eob

TODAY = date(2026, 4, 15)
PATIENT = Patient("Sam Example", ["12 Elm Street", "Springfield, IL 62701"], phone="555-0142", email="sam@example.com")
BY_NAME = {c.name: c for c in CASES}


def load(name):
    case = BY_NAME[name]
    bill = Bill.model_validate(expected_bill(case.bill))
    eob = Eob.model_validate(expected_eob(case.eob)) if case.eob else None
    return bill, eob, run_rules(bill, eob)


def amounts(text):
    return {Decimal(m.replace(",", "")) for m in re.findall(r"\$([\d,]+\.\d{2})", text)}


def allowed_amounts(bill, eob):
    """Every amount in the data, plus the balance difference the rules compute."""
    vals = {li.charge for li in bill.line_items}
    vals |= {v for v in bill.totals.model_dump().values() if isinstance(v, Decimal)}
    if eob:
        for sl in eob.service_lines:
            vals |= {sl.billed, sl.allowed, sl.insurer_paid, sl.patient_responsibility}
        vals.add(eob.totals.patient_responsibility)
        if bill.totals.patient_balance is not None and eob.totals.patient_responsibility is not None:
            vals.add(bill.totals.patient_balance - eob.totals.patient_responsibility)
    return {abs(v) for v in vals if v is not None}


# --- Itemized request ---------------------------------------------------------------


def test_itemized_request_layout():
    bill, _, _ = load("summary")
    letter = itemized_request(bill, PATIENT, TODAY)
    assert letter.kind == "itemized_request"
    t = letter.text
    assert t.startswith("Sam Example\n12 Elm Street\nSpringfield, IL 62701\n\nApril 15, 2026\n\nRiverside Medical Group")
    assert "Re: Request for an itemized bill" in t
    assert "Account number ending in 5432" in t and "****" not in t
    assert "Statement date: April 1, 2026" in t
    assert "Date of service: March 4, 2026" in t
    assert "- the CPT, HCPCS, or revenue code for each service" in t
    assert "555-0142 or sam@example.com" in t
    assert t.rstrip().endswith("Sincerely,\nSam Example")


def test_itemized_request_with_sparse_bill_has_no_blanks():
    bill, _, _ = load("summary")
    sparse = bill.model_copy(
        update={
            "provider_name": None,
            "account_number_redacted": None,
            "statement_date": None,
            "dates_of_service": bill.dates_of_service.model_copy(update={"start": None, "end": None}),
        }
    )
    t = itemized_request(sparse, Patient("Sam Example", []), TODAY).text
    assert "Billing Office" in t
    assert "Account number" not in t and "Statement date" not in t and "service:" not in t
    assert "You can reach me" not in t
    assert "None" not in t and "\n\n\n" not in t


def test_full_account_number_typed_by_patient_is_used():
    bill, _, _ = load("summary")
    patient = Patient("Sam Example", [], account_number=" 00098765432 ")
    t = itemized_request(bill, patient, TODAY).text
    assert "Account number: 00098765432" in t and "ending in" not in t


def test_date_range_when_service_dates_differ():
    bill, _, _ = load("clean")
    ranged = bill.model_copy(update={"dates_of_service": bill.dates_of_service.model_copy(update={"end": date(2026, 3, 6)})})
    assert "Dates of service: March 4, 2026 to March 6, 2026" in itemized_request(ranged, PATIENT, TODAY).text


# --- Dispute ------------------------------------------------------------------------


def test_dispute_duplicate():
    bill, eob, flags = load("duplicate")
    t = dispute(bill, eob, flags, PATIENT, TODAY).text
    assert "Re: Request for review of charges" in t
    assert "I have reviewed my bill dated April 1, 2026. I would like" in t
    assert "1. Possible duplicate charge." in t
    assert t.count("   - Complete blood count (85025) on March 4, 2026, $40.00") == 2
    assert "Insurance claim number" not in t


def test_dispute_balance_mismatch():
    bill, eob, flags = load("balance")
    t = dispute(bill, eob, flags, PATIENT, TODAY).text
    assert "and the Explanation of Benefits (EOB) from Example Health Plan" in t
    assert "Insurance claim number: C-2026-0001" in t
    assert "amount due of $95.00" in t and "responsibility as $40.00" in t and "difference of $55.00" in t
    assert "earlier balance" not in t  # high confidence: no hedge needed


def test_dispute_balance_hedges_when_bill_covers_more_dates():
    bill, eob, _ = load("balance")
    extra = dict(expected_bill(BY_NAME["balance"].bill)["line_items"][0], line_id="L9", service_date="2026-02-01")
    bill = Bill.model_validate(dict(bill.model_dump(mode="json"), line_items=bill.model_dump(mode="json")["line_items"] + [extra]))
    flags = [f for f in run_rules(bill, eob) if f.rule == "balance_mismatch"]
    assert flags[0].confidence == "medium"
    assert "earlier balance" in dispute(bill, eob, flags, PATIENT, TODAY).text


def test_dispute_denial_numbers_each_item():
    bill, eob, flags = load("denial")
    t = dispute(bill, eob, flags, PATIENT, TODAY).text
    assert "1. Amount due does not match" in t
    assert "2. Charge for a service my insurer denied: Complete blood count (85025) on March 4, 2026, $40.00." in t
    assert "(reason given: Not medically necessary (CO-50))." in t
    assert "corrected and resubmitted" in t


def test_dispute_network():
    bill, eob, flags = load("network")
    t = dispute(bill, eob, flags, PATIENT, TODAY).text
    assert 'The bill states: "Notice: This provider is out of network for your health plan."' in t
    assert "processed as in network" in t


def test_dispute_no_itemization():
    bill, eob, flags = load("summary")
    assert "The bill shows only a total." in dispute(bill, eob, flags, PATIENT, TODAY).text


def test_dispute_uses_only_selected_flags():
    bill, eob, flags = load("denial")
    chosen = [f for f in flags if f.rule == "billed_after_denial"]
    t = dispute(bill, eob, chosen, PATIENT, TODAY).text
    assert "1. Charge for a service" in t and "Amount due does not match" not in t


def test_dispute_requires_flags():
    bill, eob, _ = load("clean")
    with pytest.raises(ValueError):
        dispute(bill, eob, [], PATIENT, TODAY)


def test_dispute_rejects_flags_from_another_bill():
    _, _, flags = load("duplicate")
    bill, eob, _ = load("summary")  # has no line items
    with pytest.raises(ValueError):
        dispute(bill, eob, flags, PATIENT, TODAY)


# --- Guarantees ---------------------------------------------------------------------


@pytest.mark.parametrize("name", [c.name for c in CASES if c.expected_rules])
def test_letters_contain_only_amounts_from_the_data(name):
    bill, eob, flags = load(name)
    allowed = allowed_amounts(bill, eob)
    for letter in (dispute(bill, eob, flags, PATIENT, TODAY), itemized_request(bill, PATIENT, TODAY)):
        assert amounts(letter.text) <= allowed, letter.text
        assert "None" not in letter.text


@pytest.mark.parametrize("name", [c.name for c in CASES if c.expected_rules])
def test_letters_never_assert_the_charge_is_wrong(name):
    bill, eob, flags = load(name)
    t = dispute(bill, eob, flags, PATIENT, TODAY).text.lower()
    for phrase in ("fraud", "illegal", "i do not owe", "you overcharged", "error on your part", "lawyer", "sue"):
        assert phrase not in t


def test_letters_are_deterministic():
    bill, eob, flags = load("denial")
    assert dispute(bill, eob, flags, PATIENT, TODAY) == dispute(bill, eob, flags, PATIENT, TODAY)


# --- Patient input ------------------------------------------------------------------


def test_personal_note_included_as_written():
    bill, eob, flags = load("balance")
    note = "I paid $20.00 at the front desk on March 4."
    t = dispute(bill, eob, flags, PATIENT, TODAY, note="  " + note + "\n").text
    assert "\n\n" + note + "\n\nThank you" in t


def test_note_too_long_rejected():
    bill, _, _ = load("summary")
    with pytest.raises(ValueError):
        itemized_request(bill, PATIENT, TODAY, note="x" * (MAX_NOTE_CHARS + 1))


def test_patient_name_required():
    bill, _, _ = load("summary")
    with pytest.raises(ValueError):
        itemized_request(bill, Patient("  ", []), TODAY)


# --- PDF --------------------------------------------------------------------------------


def test_pdf_letter_matches_text_and_escapes_markup():
    import io

    import pdfplumber

    from billchecker.letters_pdf import render_pdf

    bill, eob, flags = load("denial")
    odd = bill.line_items[1].model_copy(update={"description": "Blood <b>count</b> & <font size=40>panel"})
    bill = bill.model_copy(update={"line_items": [bill.line_items[0], odd, bill.line_items[2]]})
    letter = dispute(bill, eob, flags, PATIENT, TODAY)
    pdf = render_pdf(letter)
    assert pdf.startswith(b"%PDF-")
    text = "".join(p.extract_text() for p in pdfplumber.open(io.BytesIO(pdf)).pages)
    assert "Blood <b>count</b> & <font size=40>panel" in text
    for needle in ("Sam Example", "difference of $55.00", "Sincerely,"):
        assert needle in text
