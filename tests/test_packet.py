import copy
import hashlib
import io
import os
from datetime import date, datetime, timezone

import pytest

from billchecker.letters import Patient, dispute
from billchecker.letters_pdf import render_pdf
from billchecker.models import Bill, Eob
from billchecker.packet import build_payload, canonical, public_key_b64, sign, signing_key, verify
from billchecker.rules import run_rules
from synthetic import CASES, expected_bill, expected_eob

BY_NAME = {c.name: c for c in CASES}
KEY = signing_key(os.urandom(32))
PUB = public_key_b64(KEY)


def payload():
    case = BY_NAME["denial"]
    bill, eob = Bill.model_validate(expected_bill(case.bill)), Eob.model_validate(expected_eob(case.eob))
    flags = run_rules(bill, eob)
    docs = [{"kind": "bill", "sha256": ["a" * 64]}, {"kind": "eob", "sha256": ["b" * 64]}]
    return build_payload("pkt123", datetime(2026, 4, 15, 9, 30, tzinfo=timezone.utc), bill, eob, flags, "letter text", docs)


def test_signature_round_trip():
    p = payload()
    assert verify(p, sign(p, KEY), PUB)


@pytest.mark.parametrize(
    "tamper",
    [
        lambda p: p["items"][0]["evidence"][0].__setitem__("text", "Amount due $8.00"),
        lambda p: p["items"][0]["evidence"][0].__setitem__("page", 2),
        lambda p: p["documents"][0]["sha256"].__setitem__(0, "c" * 64),
        lambda p: p.__setitem__("letter_sha256", "0" * 64),
        lambda p: p["items"].pop(),
    ],
)
def test_any_change_breaks_the_signature(tamper):
    p = payload()
    sig = sign(p, KEY)
    changed = copy.deepcopy(p)
    tamper(changed)
    assert not verify(changed, sig, PUB)


def test_wrong_key_or_garbage_signature():
    p = payload()
    other = public_key_b64(signing_key(os.urandom(32)))
    assert not verify(p, sign(p, KEY), other)
    assert not verify(p, "not-base64!!", PUB)


def test_signing_key_is_derived_deterministically():
    master = os.urandom(32)
    assert public_key_b64(signing_key(master)) == public_key_b64(signing_key(master))


def test_canonical_encoding_ignores_key_order():
    assert canonical({"b": 1, "a": [1, {"d": 2, "c": "é"}]}) == canonical({"a": [1, {"c": "é", "d": 2}], "b": 1})


def test_payload_has_no_personal_details():
    p = payload()
    text = str(p)
    for leak in ("Sam", "5432", "C-2026-0001", "Elm"):
        assert leak not in text
    assert p["items"][0]["evidence"][0]["text_sha256"] == hashlib.sha256(p["items"][0]["evidence"][0]["text"].encode()).hexdigest()


def test_letter_carries_link_and_pdf_has_qr_code():
    import pdfplumber

    case = BY_NAME["denial"]
    bill, eob = Bill.model_validate(expected_bill(case.bill)), Eob.model_validate(expected_eob(case.eob))
    url = "https://bills.example.com/verify?id=pkt123"
    letter = dispute(bill, eob, run_rules(bill, eob), Patient("Sam Example", []), date(2026, 4, 15), verify_url=url)
    assert letter.verify_url == url and letter.text.count(url) == 1
    pdf = pdfplumber.open(io.BytesIO(render_pdf(letter)))
    assert url in "".join(p.extract_text() for p in pdf.pages)
    # The QR code is drawn as many small filled squares.
    assert sum(len(p.rects) for p in pdf.pages) > 100
    plain = render_pdf(dispute(bill, eob, run_rules(bill, eob), Patient("Sam Example", []), date(2026, 4, 15)))
    assert sum(len(p.rects) for p in pdfplumber.open(io.BytesIO(plain)).pages) == 0
