import itertools
import os

import pytest

from billchecker.models import Bill, Eob
from billchecker.radar import bucket, normalize_provider, present, radar_items
from billchecker.rules import run_rules
from billchecker.store import Store
from synthetic import CASES, expected_bill, expected_eob
from test_api import PATIENT, client, clock, db_dump, llm, make_client, signup, start_case  # noqa: F401
from test_store import Clock

BY_NAME = {c.name: c for c in CASES}
KEY = os.urandom(32)
_emails = itertools.count()


@pytest.fixture
def store(pg_dsn):
    s = Store(pg_dsn, KEY, now=Clock())
    yield s
    s.close()


def reporters(store, n, provider="Riverside Medical Group", rule="duplicate_line", code="85025", cases_each=1):
    """n distinct opted-in users, each reporting the same pattern."""
    for i in range(n):
        user = store.create_user("u{}@example.com".format(next(_emails)), "h", False)
        store.set_radar_consent(user.user_id, True)
        for c in range(cases_each):
            up = store.add_upload(user.user_id, "bill", "application/pdf", 1, b"x")
            case = store.add_case(user.user_id, up.upload_id, [])
            store.put_radar_reports(case.case_id, user.user_id, normalize_provider(provider), provider,
                                    [{"flag_id": "f{}".format(c), "rule": rule, "code": code}])
            yield user, case


# --- Normalizing and items ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, key",
    [
        ("Riverside Medical Group, Inc.", "riverside medical group"),
        ("RIVERSIDE MEDICAL GROUP", "riverside medical group"),
        ("The Riverside Medical Group LLC", "riverside medical group"),
        ("St. Mary's Hospital & Clinics", "st mary s hospital and clinics"),
        ("", None),
        (None, None),
        ("Dr", None),
    ],
)
def test_normalize_provider(raw, key):
    assert normalize_provider(raw) == key


def test_radar_items_record_rule_and_code_only():
    case = BY_NAME["denial"]
    bill, eob = Bill.model_validate(expected_bill(case.bill)), Eob.model_validate(expected_eob(case.eob))
    items = radar_items(bill, run_rules(bill, eob))
    assert sorted((i["rule"], i["code"]) for i in items) == [("balance_mismatch", None), ("billed_after_denial", "85025")]


def test_buckets():
    assert [bucket(n) for n in (10, 24, 25, 60, 250)] == ["10–24", "10–24", "25–49", "50–99", "100+"]


# --- k-anonymity and counting -------------------------------------------------------------


def test_pattern_hidden_until_k_distinct_people(store):
    list(reporters(store, 9))
    key = normalize_provider("Riverside Medical Group")
    assert store.radar_patterns(key, 10) == []
    assert store.radar_providers("", 10) == []
    list(reporters(store, 1, provider="Riverside Medical Group, Inc."))  # same provider, different spelling
    [p] = present(store.radar_patterns(key, 10), 10)
    assert (p["rule"], p["code"], p["reports"]) == ("duplicate_line", "85025", "10–24")
    [row] = store.radar_providers("riverside", 10)
    assert row["provider_name"] == "Riverside Medical Group"


def test_one_person_with_many_bills_counts_once(store):
    list(reporters(store, 3, cases_each=5))
    assert store.radar_patterns(normalize_provider("Riverside Medical Group"), 4) == []
    assert store.radar_patterns(normalize_provider("Riverside Medical Group"), 3)[0]["users"] == 3


def test_patterns_without_a_code_still_count(store):
    list(reporters(store, 3, rule="balance_mismatch", code=None))
    assert store.radar_providers("", 3)[0]["patterns"] == 1


def test_disputed_reports_do_not_count_and_verdicts_survive_rechecks(store):
    rows = list(reporters(store, 3))
    key = normalize_provider("Riverside Medical Group")
    user, case = rows[0]
    store.set_radar_verdict(case.case_id, "f0", "incorrect")
    assert store.radar_patterns(key, 3) == []
    # Re-checking the case (edit, language switch) rewrites its reports but keeps the verdict.
    store.put_radar_reports(case.case_id, user.user_id, key, "Riverside Medical Group",
                            [{"flag_id": "f0", "rule": "duplicate_line", "code": "85025"}])
    assert store.radar_patterns(key, 3) == []
    store.set_radar_verdict(case.case_id, "f0", "correct")
    [p] = store.radar_patterns(key, 3)
    assert p["confirmed_users"] == 1


def test_confirmed_share_labels():
    base = {"rule": "duplicate_line", "code": "85025", "last_month": "2026-04"}
    assert present([dict(base, users=12, confirmed_users=7)], 10)[0]["confirmed"] == "most"
    assert present([dict(base, users=12, confirmed_users=1)], 10)[0]["confirmed"] == "some"
    assert present([dict(base, users=12, confirmed_users=0)], 10)[0]["confirmed"] is None


def test_withdrawing_consent_and_deleting_remove_reports(store):
    rows = list(reporters(store, 3))
    key = normalize_provider("Riverside Medical Group")
    store.set_radar_consent(rows[0][0].user_id, False)
    assert store.radar_patterns(key, 3) == []
    store.delete_case(rows[1][0].user_id, rows[1][1].case_id)
    store.delete_user(rows[2][0].user_id)
    with store.pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM radar_reports").fetchone()[0] == 0


# --- Through the API ----------------------------------------------------------------------


def test_radar_end_to_end(pg_dsn, llm, clock):  # noqa: F811
    from fastapi.testclient import TestClient

    with make_client(pg_dsn, llm, clock, radar_k=2) as first:
        r = first.post("/api/auth/register", json={"email": "a@example.com", "password": "correct horse battery", "radar_consent": True})
        assert r.json()["radar_consent"] is True
        case_a = start_case(first, llm, "denial")
        assert first.get("/api/cases/" + case_a).json()["radar"] == []  # only one reporter so far

        second = TestClient(first.app)
        second.post("/api/auth/register", json={"email": "b@example.com", "password": "correct horse battery", "radar_consent": True})
        case_b = start_case(second, llm, "denial")
        radar = second.get("/api/cases/" + case_b).json()["radar"]
        assert sorted(p["rule"] for p in radar) == ["balance_mismatch", "billed_after_denial"]
        assert all(p["reports"] == "2+" for p in radar)

        found = first.get("/api/radar", params={"q": "riverside medical"}).json()
        assert found["providers"][0]["provider_name"] == "Riverside Medical Group"
        assert first.get("/api/radar", params={"q": "nowhere hospital"}).json()["providers"] == []

        # Someone without radar consent still sees patterns but adds nothing.
        third = signup(TestClient(first.app), "c@example.com")
        case_c = start_case(third, llm, "denial")
        assert len(third.get("/api/cases/" + case_c).json()["radar"]) == 2
        with first.app.state.store.pool.connection() as conn:
            assert conn.execute("SELECT count(DISTINCT user_key) FROM radar_reports").fetchone()[0] == 2

        # "No, it was fine" from one of two reporters drops that pattern below k.
        flag = next(f for f in first.get("/api/cases/" + case_a).json()["flags"] if f["rule"] == "billed_after_denial")
        first.post("/api/cases/{}/feedback".format(case_a), json={"flag_id": flag["flag_id"], "verdict": "incorrect"})
        assert [p["rule"] for p in second.get("/api/cases/" + case_b).json()["radar"]] == ["balance_mismatch"]

        # Turning consent off removes that user's reports.
        assert second.put("/api/auth/radar-consent", json={"radar_consent": False}).json()["radar_consent"] is False
        assert first.get("/api/cases/" + case_a).json()["radar"] == []

        dump = db_dump(first, "radar_reports")
        for leak in ("a@example.com", "80.00", "Complete blood", "2026-03-04", case_a):
            assert leak not in dump


def test_radar_requires_login(client):  # noqa: F811
    from fastapi.testclient import TestClient

    assert TestClient(client.app).get("/api/radar").status_code == 401
