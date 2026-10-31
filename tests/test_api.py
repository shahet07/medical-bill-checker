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


def signup(c, email="sam@example.com", consent=True):
    r = c.post("/api/auth/register", json={"email": email, "password": "correct horse battery", "research_consent": consent})
    assert r.status_code == 201, r.text
    return c


def other_user(client):
    """A second, separately logged-in user of the same app."""
    return signup(TestClient(client.app), "other@example.com")


def make_client(pg_dsn, llm, clock, **overrides):
    settings = Settings(
        database_url=pg_dsn,
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
def client(pg_dsn, llm, clock):
    with make_client(pg_dsn, llm, clock) as c:
        yield signup(c)


def db_rows(client, sql):
    with client.app.state.store.pool.connection() as conn:
        return conn.execute(sql).fetchall()


def db_count(client, table):
    return db_rows(client, "SELECT count(*) FROM " + table)[0][0]


def db_dump(client, *tables):
    """Everything stored in the given tables (default: all), as text, for leak checks."""
    tables = tables or ("users", "sessions", "uploads", "cases", "flag_feedback", "survey", "research_cases", "events")
    return repr([db_rows(client, "SELECT * FROM " + t) for t in tables])


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
    assert "Sam Example" not in json.dumps(store.get_result(case_id))
    assert "Sam Example" not in db_dump(client)


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


def test_other_users_get_404(client, llm):
    case_id = start_case(client, llm, "clean")
    bill_id = upload(client, "bill", render_bill(BY_NAME["clean"].bill)).json()["upload_id"]
    other = other_user(client)
    assert other.get("/api/cases/" + case_id).status_code == 404
    assert other.delete("/api/cases/" + case_id).status_code == 404
    assert other.post("/api/cases", json={"bill_upload_id": bill_id}).status_code == 404
    assert client.get("/api/cases/" + case_id).status_code == 200


def test_delete_removes_everything(client, llm):
    case_id = start_case(client, llm, "denial")
    assert client.delete("/api/cases/" + case_id).status_code == 204
    assert client.get("/api/cases/" + case_id).status_code == 404
    # The case and both uploads (bill and EOB) are gone.
    assert db_count(client, "cases") == 0 and db_count(client, "uploads") == 0


def test_files_go_after_24_hours_results_after_90_days(client, llm, clock):
    case_id = start_case(client, llm, "clean")
    clock.advance(hours=25)
    assert client.app.state.store.cleanup()["files_purged"] == 2
    got = client.get("/api/cases/" + case_id).json()
    assert got["status"] == "ready" and got["flags"] == []  # results still readable
    clock.advance(days=90)
    assert client.get("/api/cases/" + case_id).status_code == 401  # the 14-day login expired too
    client.post("/api/auth/login", json={"email": "sam@example.com", "password": "correct horse battery"})
    assert client.get("/api/cases/" + case_id).status_code == 404
    client.app.state.store.cleanup()
    assert db_count(client, "cases") == 0 and db_count(client, "uploads") == 0


def test_malformed_ids_are_404(client):
    assert client.get("/api/cases/../../etc/passwd").status_code == 404
    assert client.get("/api/cases/abc").status_code == 404


# --- Cookies, headers, rate limits, logs -------------------------------------------------


def test_session_cookie_flags(pg_dsn, llm, clock):
    with make_client(pg_dsn, llm, clock, secure_cookies=True) as c:
        r = c.post("/api/auth/register", json={"email": "s@example.com", "password": "correct horse battery"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie


def test_security_headers(client):
    r = client.get("/api/cases/" + "0" * 32)
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_no_api_docs_exposed(client):
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


def test_rate_limit(pg_dsn, llm, clock):
    from billchecker.api import DEFAULT_LIMITS

    with make_client(pg_dsn, llm, clock, limits=dict(DEFAULT_LIMITS, upload=(2, 3600))) as c:
        signup(c)
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
    # Only 35 of the 40 owed is on the readable EOB and the blood draw is on the unreadable one,
    # so whole-claim checks are skipped rather than raising false flags.
    assert got["flags"] == []


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
    [row] = rows["survey"]
    assert (row["helpful"], row["most_useful"], row["flag_count"], row["had_eob"]) == (4, "letter", 2, True)
    stored = db_dump(client, "flag_feedback", "survey")
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
    other = other_user(client)
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


# --- Editing the bill ----------------------------------------------------------------------


def lines_as_edit(bill):
    return [
        {k: li[k] for k in ("line_id", "service_date", "description", "code", "units", "charge")}
        for li in bill["line_items"]
    ]


def test_edit_fixes_a_misread_line_and_reruns_checks(client, llm):
    case_id = start_case(client, llm, "duplicate")
    got = client.get("/api/cases/" + case_id).json()
    assert [f["rule"] for f in got["flags"]] == ["duplicate_line"]
    lines = lines_as_edit(got["bill"])
    del lines[2]  # the second blood count was a misread
    body = {"line_items": lines, "totals": {"billed": "205.00", "adjustments": "-165.00", "patient_balance": "40.00"}}
    r = client.put("/api/cases/{}/bill".format(case_id), json=body)
    assert r.status_code == 200
    got = client.get("/api/cases/" + case_id).json()
    assert got["status"] == "ready" and got["flags"] == [] and got["user_edited"] is True
    assert [li["line_id"] for li in got["bill"]["line_items"]] == ["L1", "L2", "L3"]
    # Unchanged lines keep the document's own text.
    assert got["bill"]["line_items"][0]["source_text"].startswith("03/04/2026 99213")


def test_edited_and_added_lines_are_marked_as_entered_by_user(client, llm):
    case_id = start_case(client, llm, "clean")
    got = client.get("/api/cases/" + case_id).json()
    lines = lines_as_edit(got["bill"])
    lines[1]["charge"] = "45.00"
    lines.append({"service_date": "2026-03-04", "description": "Chest X-ray", "code": "71046", "units": "1", "charge": "120.00"})
    body = {"line_items": lines, "totals": {"billed": "330.00", "adjustments": "-165.00", "patient_balance": "160.00"}}
    client.put("/api/cases/{}/bill".format(case_id), json=body)
    got = client.get("/api/cases/" + case_id).json()
    items = got["bill"]["line_items"]
    assert items[1]["source_text"].startswith("Entered by you:") and items[1]["charge"] == "45.00"
    assert items[3]["source_text"].startswith("Entered by you:") and items[3]["code_type"] == "CPT"
    rules = sorted(f["rule"] for f in got["flags"])
    assert rules == ["balance_mismatch", "charge_mismatch", "not_on_eob"]
    evidence = [e["text"] for f in got["flags"] for e in f["evidence"] if e["ref"] == "L4"]
    assert evidence and all(t.startswith("Entered by you:") for t in evidence)


def test_edit_validation(client, llm):
    case_id = start_case(client, llm, "clean")
    url = "/api/cases/{}/bill".format(case_id)
    bad_charge = {"line_items": [{"description": "x", "charge": "1.234"}], "totals": {}}
    assert client.put(url, json=bad_charge).status_code == 422
    empty_desc = {"line_items": [{"description": "", "charge": "1.00"}], "totals": {}}
    assert client.put(url, json=empty_desc).status_code == 422
    assert other_user(client).put(url, json={"line_items": [], "totals": {}}).status_code == 404


@pytest.mark.parametrize(
    "code, kind", [("99213", "CPT"), ("99213-25", "CPT"), ("J1100", "HCPCS"), ("0450", "REV"), ("ABC", "OTHER"), (None, None)]
)
def test_guess_code_type(code, kind):
    from billchecker.api import guess_code_type

    assert guess_code_type(code) == kind


def test_case_language_reaches_explanations(client, llm):
    case = BY_NAME["clean"]
    llm.queues["bill"].append(expected_bill(case.bill))
    llm.queues["explain"].append(LLMResponse(text=None, stop_reason="refusal"))
    bill_id = upload(client, "bill", render_bill(case.bill)).json()["upload_id"]
    case_id = client.post("/api/cases", json={"bill_upload_id": bill_id, "language": "es"}).json()["case_id"]
    got = client.get("/api/cases/" + case_id).json()
    assert got["language"] == "es"
    assert got["explanations"]["lines"]["L1"]["text"].startswith("Aparece en su factura")
    assert client.post("/api/cases", json={"bill_upload_id": bill_id, "language": "fr"}).status_code == 422


def test_switching_language_rewrites_explanations_only(client, llm):
    case_id = start_case(client, llm, "denial")
    before = client.get("/api/cases/" + case_id).json()
    llm.queues["explain"].append(LLMResponse(text=None, stop_reason="refusal"))  # forces Spanish templates
    r = client.put("/api/cases/{}/language".format(case_id), json={"language": "es"})
    assert r.status_code == 200
    after = client.get("/api/cases/" + case_id).json()
    assert after["language"] == "es" and after["status"] == "ready"
    assert after["flags"] == before["flags"] and after["bill"] == before["bill"]
    assert after["explanations"]["lines"]["L1"]["text"].startswith("Aparece en su factura")
    # Same language again: nothing to redo.
    assert client.put("/api/cases/{}/language".format(case_id), json={"language": "es"}).json()["status"] == "ready"
    assert client.put("/api/cases/{}/language".format(case_id), json={"language": "de"}).status_code == 422


def test_reference_data_reaches_results(pg_dsn, llm, clock):
    from decimal import Decimal

    from billchecker.reference import PairEdit, Reference

    ref = Reference(
        pairs={("85025", "36415"): [PairEdit(date(2020, 1, 1), None, "0")]},
        prices={"99213": Decimal("92.50")},
        prices_label="Test rate",
    )
    with make_client(pg_dsn, llm, clock, reference=ref) as c:
        signup(c)
        case_id = start_case(c, llm, "clean")
        got = c.get("/api/cases/" + case_id).json()
    assert [f["rule"] for f in got["flags"]] == ["unbundled_pair"]
    assert got["price_context"] == {"L1": {"reference_price": "92.50"}} and got["prices_label"] == "Test rate"


# --- Questions (RAG) ----------------------------------------------------------------------------


def test_ask_with_and_without_a_bill(client, llm):
    from billchecker.rag import ANSWER_SCHEMA

    case_id = start_case(client, llm, "denial")
    original = llm.generate

    def generate(system, content, schema):
        # RoutingLLM only knows the extraction/explanation schemas; answer questions here.
        if schema is ANSWER_SCHEMA:
            answer = {"can_answer": True, "answer": "An EOB is a statement from your insurer. It is not a bill.", "citations": ["S1"]}
            return LLMResponse(text=json.dumps(answer), stop_reason="end_turn")
        return original(system, content, schema)

    llm.generate = generate
    r = client.post("/api/ask", json={"question": "What is an EOB?"})
    assert r.status_code == 200 and r.json()["fallback"] is False
    assert r.json()["sources"][0]["source_url"].startswith("https://")
    r = client.post("/api/ask", json={"question": "Why does my bill not match?", "case_id": case_id, "language": "es"})
    assert r.status_code == 200
    assert client.post("/api/ask", json={"question": "x" * 501}).status_code == 422
    assert client.post("/api/ask", json={"question": "hi", "case_id": "0" * 32}).status_code == 404
    assert other_user(client).post("/api/ask", json={"question": "hi", "case_id": case_id}).status_code == 404
    events = db_dump(client, "events")
    assert "What is an EOB" not in events and "question_asked" in events


def test_ask_requires_login(client):
    assert TestClient(client.app).post("/api/ask", json={"question": "What is an EOB?"}).status_code == 401


# --- Call rehearsal ------------------------------------------------------------------------------


def test_rehearsal_flow_and_nothing_stored(client, llm):
    from billchecker.rehearsal import REPLY_SCHEMA, SCORE_SCHEMA

    case_id = start_case(client, llm, "denial")
    original = llm.generate

    def generate(system, content, schema):
        if schema is REPLY_SCHEMA:
            return LLMResponse(text=json.dumps({"reply": "Let me look at the balance of $80.00.", "call_ended": False}), stop_reason="end_turn")
        if schema is SCORE_SCHEMA:
            score = {"scores": {"clarity": 4, "evidence": 4, "asks": 3, "persistence": 3}, "strengths": ["Clear opening."],
                     "improvements": ["Ask for a reference number."], "try_saying": ["Can I get a reference number?"], "citations": ["S1"]}
            return LLMResponse(text=json.dumps(score), stop_reason="end_turn")
        return original(system, content, schema)

    llm.generate = generate
    url = "/api/cases/{}/rehearse".format(case_id)
    start = client.post(url, json={"counterpart": "billing_office"}).json()
    assert "Riverside Medical Group" in start["reply"] and start["suggested_opener"].startswith("Hi, I'm calling")
    said = "My bill says $80.00 but my EOB says $25.00. Pretend secret phrase 7f3k."
    turns = [{"role": "rep", "text": start["reply"]}, {"role": "patient", "text": said}]
    r = client.post(url, json={"counterpart": "billing_office", "turns": turns}).json()
    assert r["reply"] == "Let me look at the balance of $80.00." and r["fallback"] is False
    turns.append({"role": "rep", "text": r["reply"]})
    turns.append({"role": "patient", "text": "Thanks, bye."})
    score = client.post(url + "/score", json={"counterpart": "billing_office", "turns": turns}).json()
    assert score["scores"]["clarity"] == 4 and score["sources"]
    assert "7f3k" not in db_dump(client)  # practice calls are never stored
    counts = client.app.state.store.event_counts()
    assert counts.get("rehearsal_started") == 1 and counts.get("rehearsal_scored") == 1


def test_rehearsal_validation(client, llm):
    case_id = start_case(client, llm, "denial")
    url = "/api/cases/{}/rehearse".format(case_id)
    rep_last = [{"role": "patient", "text": "hi"}, {"role": "rep", "text": "hello"}]
    assert client.post(url, json={"turns": rep_last}).status_code == 422
    assert client.post(url, json={"turns": [{"role": "boss", "text": "hi"}]}).status_code == 422
    assert client.post(url + "/score", json={"turns": []}).status_code == 422
    assert other_user(client).post(url, json={}).status_code == 404
