import copy
import json
import logging
import os
from datetime import date

import pytest
from fastapi.testclient import TestClient

from billchecker import pipeline
from billchecker.api import Settings, create_app
from billchecker.explanation import SCHEMA as EXPLAIN_SCHEMA
from billchecker.extraction import BILL_SCHEMA, EOB_SCHEMA
from billchecker.llm import LLMResponse, LLMUnavailable
from synthetic import CASES, expected_bill, expected_eob, render_bill, render_eob
from test_store import Clock

BY_NAME = {c.name: c for c in CASES}
PATIENT = {"name": "Sam Example", "address_lines": ["12 Elm Street"], "email": "sam@example.com"}


class RoutingLLM:
    """Answers by which schema is requested. Each queue entry is JSON-able data,
    an LLMResponse, or an exception to raise."""

    def __init__(self):
        self.queues = {"bill": [], "eob": [], "explain": []}
        self.default_explain = {"lines": [], "flags": []}

    def generate(self, system, content, schema):
        kind = {id(BILL_SCHEMA): "bill", id(EOB_SCHEMA): "eob", id(EXPLAIN_SCHEMA): "explain"}[id(schema)]
        queue = self.queues[kind]
        item = queue.pop(0) if queue else (self.default_explain if kind == "explain" else None)
        if item is None:
            raise AssertionError("unexpected {} call".format(kind))
        if isinstance(item, Exception):
            raise item
        if isinstance(item, LLMResponse):
            return item
        return LLMResponse(text=json.dumps(item), stop_reason="end_turn")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def llm():
    return RoutingLLM()


def make_client(tmp_path, llm, clock, **overrides):
    settings = Settings(
        data_dir=tmp_path / "data",
        key=os.urandom(32),
        llm=llm,
        secure_cookies=False,
        inline_jobs=True,
        cleanup_interval=None,
        now=clock,
        today=lambda: date(2026, 4, 15),
    )
    for k, v in overrides.items():
        setattr(settings, k, v)
    return TestClient(create_app(settings))


@pytest.fixture
def client(tmp_path, llm, clock):
    with make_client(tmp_path, llm, clock) as c:
        yield c


def upload(client, kind, data, name="file.pdf"):
    return client.post("/api/uploads", data={"kind": kind}, files={"file": (name, data, "application/octet-stream")})


def start_case(client, llm, name, bill_json=None, eob_json=None):
    case = BY_NAME[name]
    llm.queues["bill"].append(bill_json or expected_bill(case.bill))
    bill_id = upload(client, "bill", render_bill(case.bill)).json()["upload_id"]
    body = {"bill_upload_id": bill_id}
    if case.eob:
        llm.queues["eob"].append(eob_json or expected_eob(case.eob))
        body["eob_upload_id"] = upload(client, "eob", render_eob(case.eob)).json()["upload_id"]
    r = client.post("/api/cases", json=body)
    assert r.status_code == 201, r.text
    return r.json()["case_id"]


# --- Happy path -------------------------------------------------------------------------


def test_full_flow_denial_case(client, llm):
    r = upload(client, "bill", render_bill(BY_NAME["denial"].bill))
    assert r.status_code == 201
    assert r.json()["page_count"] == 1 and len(r.json()["upload_id"]) == 32
    case_id = start_case(client, llm, "denial")
    got = client.get("/api/cases/" + case_id).json()
    assert got["status"] == "ready"
    assert sorted(f["rule"] for f in got["flags"]) == ["balance_mismatch", "billed_after_denial"]
    assert got["bill"]["line_items"][0]["charge"] == "150.00"  # exact decimal string
    assert got["eob_status"] == "ok"
    assert set(got["explanations"]["lines"]) == {"L1", "L2", "L3"}


def test_bill_only_case(client, llm):
    case_id = start_case(client, llm, "duplicate")
    got = client.get("/api/cases/" + case_id).json()
    assert got["status"] == "ready" and got["eob"] is None and got["eob_status"] == "none"
    assert [f["rule"] for f in got["flags"]] == ["duplicate_line"]


def test_dispute_letter_with_selected_flags(client, llm):
    case_id = start_case(client, llm, "denial")
    flags = client.get("/api/cases/" + case_id).json()["flags"]
    chosen = [f["flag_id"] for f in flags if f["rule"] == "billed_after_denial"]
    r = client.post("/api/cases/{}/letter".format(case_id), json={"kind": "dispute", "patient": PATIENT, "flag_ids": chosen})
    assert r.status_code == 200
    text = r.json()["text"]
    assert "April 15, 2026" in text and "1. Charge for a service my insurer denied" in text
    assert "Amount due does not match" not in text


def test_itemized_letter(client, llm):
    case_id = start_case(client, llm, "summary")
    r = client.post("/api/cases/{}/letter".format(case_id), json={"kind": "itemized_request", "patient": PATIENT})
    assert r.status_code == 200 and "Request for an itemized bill" in r.json()["text"]


def test_letter_errors(client, llm):
    case_id = start_case(client, llm, "clean")
    url = "/api/cases/{}/letter".format(case_id)
    assert client.post(url, json={"kind": "dispute", "patient": PATIENT}).json()["detail"]["error"] == "no_flags"
    r = client.post(url, json={"kind": "dispute", "patient": PATIENT, "flag_ids": ["made-up"]})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "unknown_flag"
    assert client.post(url, json={"kind": "dispute", "patient": {"name": ""}}).status_code == 422
    assert client.post(url, json={"kind": "other", "patient": PATIENT}).status_code == 422


def test_patient_details_are_not_stored(client, llm):
    case_id = start_case(client, llm, "denial")
    client.post("/api/cases/{}/letter".format(case_id), json={"kind": "dispute", "patient": PATIENT})
    store = client.app.state.store
    for path in store.blobs.iterdir():
        assert b"Sam Example" not in store.get_blob(path.name)
    assert b"Sam Example" not in (store.root / "index.sqlite3").read_bytes()


# --- Confirmation and failures ----------------------------------------------------------


def test_totals_mismatch_needs_confirmation_then_confirm(client, llm):
    bad = copy.deepcopy(expected_bill(BY_NAME["balance"].bill))
    bad["totals"]["billed"] = "999.00"
    case_id = start_case(client, llm, "balance", bill_json=bad)
    got = client.get("/api/cases/" + case_id).json()
    assert got["status"] == "needs_confirmation"
    assert got["bill"]["totals"]["billed"] is None and "999.00" in got["problems"][0]
    url = "/api/cases/{}/letter".format(case_id)
    assert client.post(url, json={"kind": "itemized_request", "patient": PATIENT}).status_code == 409

    r = client.post("/api/cases/{}/confirm".format(case_id), json={"billed": "205.00", "patient_balance": "95.00"})
    assert r.status_code == 200
    got = client.get("/api/cases/" + case_id).json()
    assert got["status"] == "ready" and got["problems"] == []
    assert got["bill"]["totals"]["billed"] == "205.00"
    assert [f["rule"] for f in got["flags"]] == ["balance_mismatch"]
    assert client.post("/api/cases/{}/confirm".format(case_id), json={}).status_code == 409


def test_confirm_rejects_bad_amounts(client, llm):
    bad = copy.deepcopy(expected_bill(BY_NAME["balance"].bill))
    bad["totals"]["billed"] = "999.00"
    case_id = start_case(client, llm, "balance", bill_json=bad)
    r = client.post("/api/cases/{}/confirm".format(case_id), json={"billed": "12.345"})
    assert r.status_code == 422


def test_unreadable_bill_fails_with_message(client, llm):
    llm.queues["bill"] += ["not json", "still not json"]
    bill_id = upload(client, "bill", render_bill(BY_NAME["clean"].bill)).json()["upload_id"]
    case_id = client.post("/api/cases", json={"bill_upload_id": bill_id}).json()["case_id"]
    got = client.get("/api/cases/" + case_id).json()
    assert (got["status"], got["error_code"]) == ("failed", "unreadable")
    assert "clearer photo" in got["error_message"]


def test_unreadable_eob_continues_without_it(client, llm):
    llm.queues["eob"].append("garbage")  # first attempt; start_case adds the retry
    case_id = start_case(client, llm, "balance", eob_json="garbage")
    got = client.get("/api/cases/" + case_id).json()
    assert got["status"] == "ready" and got["eob_status"] == "unreadable"
    assert got["flags"] == []  # balance check needs the EOB


def test_llm_outage_stays_queued_then_recovers(client, llm):
    case = BY_NAME["clean"]
    llm.queues["bill"].append(LLMUnavailable("down"))
    bill_id = upload(client, "bill", render_bill(case.bill)).json()["upload_id"]
    case_id = client.post("/api/cases", json={"bill_upload_id": bill_id}).json()["case_id"]
    got = client.get("/api/cases/" + case_id).json()
    assert (got["status"], got["error_code"]) == ("queued", "llm_unavailable")

    llm.queues["bill"].append(expected_bill(case.bill))
    client.app.state.runner.run(case_id)  # what the retry timer does
    assert client.get("/api/cases/" + case_id).json()["status"] == "ready"


def test_llm_outage_gives_up_after_max_attempts(client, llm):
    llm.queues["bill"] += [LLMUnavailable("down")] * pipeline.MAX_ATTEMPTS
    bill_id = upload(client, "bill", render_bill(BY_NAME["clean"].bill)).json()["upload_id"]
    case_id = client.post("/api/cases", json={"bill_upload_id": bill_id}).json()["case_id"]
    for _ in range(pipeline.MAX_ATTEMPTS - 1):
        client.app.state.runner.run(case_id)
    got = client.get("/api/cases/" + case_id).json()
    assert (got["status"], got["error_code"]) == ("failed", "llm_unavailable")


# --- Uploads ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data, code",
    [(b"hello", "unsupported_type"), (b"%PDF-1.4 broken", "unreadable"), (b"\x00\x00\x00\x18ftypheic" + b"0" * 32, "unreadable")],
)
def test_bad_uploads_rejected(client, data, code):
    r = upload(client, "bill", data)
    assert r.status_code == 422 and r.json()["detail"]["error"] == code


def test_upload_kind_must_match(client):
    eob_id = upload(client, "eob", render_eob(BY_NAME["clean"].eob)).json()["upload_id"]
    r = client.post("/api/cases", json={"bill_upload_id": eob_id})
    assert r.status_code == 404
    assert upload(client, "invoice", render_bill(BY_NAME["clean"].bill)).status_code == 422


# --- Sessions, deletion, expiry ------------------------------------------------------------


def test_other_sessions_get_404(client, llm, tmp_path, clock):
    case_id = start_case(client, llm, "clean")
    bill_id = upload(client, "bill", render_bill(BY_NAME["clean"].bill)).json()["upload_id"]
    other = TestClient(client.app)
    assert other.get("/api/cases/" + case_id).status_code == 404
    assert other.delete("/api/cases/" + case_id).status_code == 404
    assert other.post("/api/cases", json={"bill_upload_id": bill_id}).status_code == 404
    assert client.get("/api/cases/" + case_id).status_code == 200


def test_delete_removes_everything(client, llm):
    case_id = start_case(client, llm, "denial")
    assert client.delete("/api/cases/" + case_id).status_code == 204
    assert client.get("/api/cases/" + case_id).status_code == 404
    # The case result and both uploads (bill and EOB) are gone.
    assert list(client.app.state.store.blobs.iterdir()) == []


def test_results_expire_after_24_hours(client, llm, clock):
    case_id = start_case(client, llm, "clean")
    clock.advance(hours=25)
    assert client.get("/api/cases/" + case_id).status_code == 404
    client.app.state.store.cleanup()
    assert list(client.app.state.store.blobs.iterdir()) == []


def test_malformed_ids_are_404(client):
    assert client.get("/api/cases/../../etc/passwd").status_code == 404
    assert client.get("/api/cases/abc").status_code == 404


# --- Cookies, headers, rate limits, logs -------------------------------------------------


def test_session_cookie_flags(tmp_path, llm, clock):
    with make_client(tmp_path, llm, clock, secure_cookies=True) as c:
        r = upload(c, "bill", render_bill(BY_NAME["clean"].bill))
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie


def test_security_headers(client):
    r = client.get("/api/cases/" + "0" * 32)
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_no_api_docs_exposed(client):
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


def test_rate_limit(tmp_path, llm, clock):
    with make_client(tmp_path, llm, clock, limits={"upload": (2, 3600), "case": (10, 3600), "letter": (10, 3600), "confirm": (10, 3600)}) as c:
        data = render_bill(BY_NAME["clean"].bill)
        assert [upload(c, "bill", data).status_code for _ in range(3)] == [201, 201, 429]


def test_logs_contain_no_document_data(client, llm, caplog):
    caplog.set_level(logging.DEBUG)
    lines = {"lines": [{"line_id": "L1", "explanation": "It costs $999.00."}], "flags": []}
    llm.queues["explain"].append(lines)
    start_case(client, llm, "denial")
    text = caplog.text
    assert "status=ready" in text
    for leak in ("150.00", "999", "Complete blood", "Riverside", "Not medically", "Sam Example"):
        assert leak not in text


# --- Several files and several EOBs ---------------------------------------------------------


def split_eob(case):
    """The clean case's EOB as two claims: first two lines, then the last."""
    full = expected_eob(case.eob)
    a, b = copy.deepcopy(full), copy.deepcopy(full)
    a["service_lines"], b["service_lines"] = full["service_lines"][:2], [dict(full["service_lines"][2], line_id="E1")]
    a["claim_id"], b["claim_id"] = "C-1", "C-2"
    a["totals"] = {"patient_responsibility": "35.00", "source": None}
    b["totals"] = {"patient_responsibility": "5.00", "source": None}
    return a, b


def test_bill_from_several_photos(client, llm):
    from synthetic import photo

    pdf = render_bill(BY_NAME["clean"].bill)
    files = [("file", ("p1.jpg", photo(pdf, 1), "image/jpeg")), ("file", ("p2.jpg", photo(pdf, 2), "image/jpeg"))]
    r = client.post("/api/uploads", data={"kind": "bill"}, files=files)
    assert r.status_code == 201 and r.json()["page_count"] == 2
    llm.queues["bill"].append(expected_bill(BY_NAME["clean"].bill))
    case_id = client.post("/api/cases", json={"bill_upload_id": r.json()["upload_id"]}).json()["case_id"]
    assert client.get("/api/cases/" + case_id).json()["status"] == "ready"


def test_case_with_two_eobs_is_compared_against_their_sum(client, llm):
    case = BY_NAME["clean"]
    a, b = split_eob(case)
    llm.queues["bill"].append(expected_bill(case.bill))
    llm.queues["eob"] += [a, b]
    bill_id = upload(client, "bill", render_bill(case.bill)).json()["upload_id"]
    eob_ids = [upload(client, "eob", render_eob(case.eob)).json()["upload_id"] for _ in range(2)]
    case_id = client.post("/api/cases", json={"bill_upload_id": bill_id, "eob_upload_ids": eob_ids}).json()["case_id"]
    got = client.get("/api/cases/" + case_id).json()
    assert got["status"] == "ready" and got["eob_status"] == "ok"
    assert got["flags"] == []  # 35 + 5 = 40 matches the bill's amount due
    assert got["eob"]["claim_id"] == "C-1, C-2"
    assert [sl["line_id"] for sl in got["eob"]["service_lines"]] == ["E1", "E2", "E3"]
    assert [sl["source_page"] for sl in got["eob"]["service_lines"]] == [1, 1, 2]


def test_one_unreadable_eob_of_two_is_partial(client, llm):
    case = BY_NAME["clean"]
    a, _ = split_eob(case)
    llm.queues["bill"].append(expected_bill(case.bill))
    llm.queues["eob"] += [a, "garbage", "garbage"]
    bill_id = upload(client, "bill", render_bill(case.bill)).json()["upload_id"]
    eob_ids = [upload(client, "eob", render_eob(case.eob)).json()["upload_id"] for _ in range(2)]
    case_id = client.post("/api/cases", json={"bill_upload_id": bill_id, "eob_upload_ids": eob_ids}).json()["case_id"]
    got = client.get("/api/cases/" + case_id).json()
    assert got["eob_status"] == "partial"
    assert [f["rule"] for f in got["flags"]] == ["balance_mismatch"]  # 35 of 40 found


def test_too_many_eobs_rejected(client):
    ids = [upload(client, "eob", render_eob(BY_NAME["clean"].eob)).json()["upload_id"] for _ in range(6)]
    bill_id = upload(client, "bill", render_bill(BY_NAME["clean"].bill)).json()["upload_id"]
    r = client.post("/api/cases", json={"bill_upload_id": bill_id, "eob_upload_ids": ids})
    assert r.status_code == 422


# --- Feedback ---------------------------------------------------------------------------------


def test_flag_feedback_and_survey_are_stored_without_case_data(client, llm):
    case_id = start_case(client, llm, "denial")
    flags = client.get("/api/cases/" + case_id).json()["flags"]
    url = "/api/cases/{}/feedback".format(case_id)
    assert client.post(url, json={"flag_id": flags[0]["flag_id"], "verdict": "incorrect"}).status_code == 204
    assert client.post(url, json={"flag_id": flags[0]["flag_id"], "verdict": "correct"}).status_code == 204  # changed mind
    assert client.post(url, json={"flag_id": flags[1]["flag_id"], "verdict": "unsure"}).status_code == 204
    assert client.post("/api/cases/{}/survey".format(case_id), json={"helpful": 4, "most_useful": "letter"}).status_code == 204

    store = client.app.state.store
    rows = store.feedback_rows()
    assert sorted((r["rule"], r["verdict"]) for r in rows["flags"]) == [
        ("balance_mismatch", "correct"),
        ("billed_after_denial", "unsure"),
    ]
    assert rows["survey"] == [{"helpful": 4, "most_useful": "letter", "flag_count": 2, "had_eob": 1}]
    import sqlite3

    db = sqlite3.connect(str(store.root / "index.sqlite3"))
    stored = repr(db.execute("SELECT * FROM flag_feedback").fetchall() + db.execute("SELECT * FROM survey").fetchall())
    assert case_id not in stored and flags[0]["flag_id"] not in stored and "L2" not in stored


def test_feedback_survives_case_deletion(client, llm):
    case_id = start_case(client, llm, "duplicate")
    flag_id = client.get("/api/cases/" + case_id).json()["flags"][0]["flag_id"]
    client.post("/api/cases/{}/feedback".format(case_id), json={"flag_id": flag_id, "verdict": "correct"})
    client.delete("/api/cases/" + case_id)
    assert len(client.app.state.store.feedback_rows()["flags"]) == 1


def test_feedback_validation(client, llm):
    case_id = start_case(client, llm, "duplicate")
    url = "/api/cases/{}/feedback".format(case_id)
    assert client.post(url, json={"flag_id": "made-up", "verdict": "correct"}).status_code == 404
    flag_id = client.get("/api/cases/" + case_id).json()["flags"][0]["flag_id"]
    assert client.post(url, json={"flag_id": flag_id, "verdict": "maybe"}).status_code == 422
    survey = "/api/cases/{}/survey".format(case_id)
    assert client.post(survey, json={"helpful": 6, "most_useful": "letter"}).status_code == 422
    other = TestClient(client.app)
    assert other.post(url, json={"flag_id": flag_id, "verdict": "correct"}).status_code == 404


def test_letter_as_pdf(client, llm):
    case_id = start_case(client, llm, "denial")
    r = client.post("/api/cases/{}/letter".format(case_id), json={"kind": "dispute", "patient": PATIENT, "format": "pdf"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert 'filename="dispute.pdf"' in r.headers["content-disposition"]
    assert r.content.startswith(b"%PDF-")


@pytest.mark.parametrize(
    "name, kind, extra, expect",
    [
        ("summary", "financial_assistance", {}, "Request for financial assistance"),
        ("summary", "payment_plan", {"monthly_amount": "50.00"}, "I can pay $50.00 per month"),
        ("denial", "insurer_appeal", {}, "Attn: Claims Review and Appeals"),
    ],
)
def test_new_letter_kinds(client, llm, name, kind, extra, expect):
    case_id = start_case(client, llm, name)
    body = dict({"kind": kind, "patient": dict(PATIENT, member_id="M1")}, **extra)
    r = client.post("/api/cases/{}/letter".format(case_id), json=body)
    assert r.status_code == 200, r.text
    assert expect in r.json()["text"]


def test_appeal_without_denial_rejected(client, llm):
    case_id = start_case(client, llm, "clean")
    r = client.post("/api/cases/{}/letter".format(case_id), json={"kind": "insurer_appeal", "patient": PATIENT})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "no_denials"
