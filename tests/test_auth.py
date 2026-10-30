import json

import pytest
from fastapi.testclient import TestClient

from billchecker.api import DEFAULT_LIMITS
from test_api import BY_NAME, PATIENT, client, clock, db_count, db_dump, llm, make_client, signup, start_case  # noqa: F401

PASSWORD = "correct horse battery"


def fresh(client):  # noqa: F811
    """A logged-out browser for the same app."""
    return TestClient(client.app)


def login(c, email="sam@example.com", password=PASSWORD):
    return c.post("/api/auth/login", json={"email": email, "password": password})


# --- Register / login / logout -------------------------------------------------------------


def test_register_logs_in_and_me(client):  # noqa: F811
    me = client.get("/api/auth/me").json()
    assert me["email"] == "sam@example.com" and me["research_consent"] is True


def test_login_logout(client):  # noqa: F811
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    r = login(client, "SAM@example.com ")
    assert r.status_code == 200 and r.json()["email"] == "sam@example.com"
    assert client.get("/api/auth/me").status_code == 200


def test_logout_invalidates_the_token_server_side(client):  # noqa: F811
    token = client.cookies.get("bc_session")
    client.post("/api/auth/logout")
    stolen = fresh(client)
    stolen.cookies.set("bc_session", token)
    assert stolen.get("/api/auth/me").status_code == 401


def test_wrong_password_and_unknown_email_look_the_same(client):  # noqa: F811
    c = fresh(client)
    a = login(c, password="wrong password!!")
    b = login(c, email="nobody@example.com")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": {"error": "bad_login", "message": "Email or password is incorrect."}}


def test_account_locks_after_ten_failures(client, clock):  # noqa: F811
    c = fresh(client)
    for _ in range(10):
        assert login(c, password="wrong password!!").status_code == 401
    r = login(c)  # right password, but locked
    assert r.status_code == 429 and r.json()["detail"]["error"] == "locked"
    clock.advance(minutes=16)
    assert login(c).status_code == 200


def test_login_attempts_limited_per_ip(pg_dsn, llm, clock):  # noqa: F811
    with make_client(pg_dsn, llm, clock, limits=dict(DEFAULT_LIMITS, login=(3, 900))) as c:
        codes = [login(c, email="x{}@example.com".format(i)).status_code for i in range(4)]
    assert codes == [401, 401, 401, 429]


@pytest.mark.parametrize(
    "email, password, code",
    [
        ("not-an-email", PASSWORD, "invalid_email"),
        ("a@b", PASSWORD, "invalid_email"),
        ("new@example.com", "short", "weak_password"),
        ("longname@example.com", "longname@example.com", "weak_password"),
    ],
)
def test_register_validation(client, email, password, code):  # noqa: F811
    r = fresh(client).post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 422 and r.json()["detail"]["error"] == code


def test_duplicate_email(client):  # noqa: F811
    r = fresh(client).post("/api/auth/register", json={"email": "Sam@Example.com", "password": PASSWORD})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "email_taken"


def test_passwords_stored_hashed(client):  # noqa: F811
    dump = db_dump(client, "users", "sessions")
    assert PASSWORD not in dump and "$argon2id$" in dump
    assert client.cookies.get("bc_session") not in dump


# --- Everything needs a login ---------------------------------------------------------------


@pytest.mark.parametrize(
    "method, path",
    [
        ("get", "/api/cases"),
        ("get", "/api/cases/" + "0" * 32),
        ("post", "/api/cases"),
        ("post", "/api/uploads"),
        ("delete", "/api/cases/" + "0" * 32),
        ("get", "/api/auth/me"),
        ("put", "/api/auth/consent"),
    ],
)
def test_endpoints_require_login(client, method, path):  # noqa: F811
    r = getattr(fresh(client), method)(path)
    assert r.status_code == 401, (path, r.status_code)


def test_page_and_assets_do_not_require_login(client):  # noqa: F811
    c = fresh(client)
    assert c.get("/").status_code == 200 and c.get("/static/app.js").status_code == 200


# --- Account management -------------------------------------------------------------------


def test_change_password_logs_out_other_sessions(client):  # noqa: F811
    laptop = fresh(client)
    login(laptop)
    r = client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "a brand new passphrase"})
    assert r.status_code == 204
    assert client.get("/api/auth/me").status_code == 200  # this session stays
    assert laptop.get("/api/auth/me").status_code == 401  # others are logged out
    assert login(fresh(client), password="a brand new passphrase").status_code == 200
    bad = client.post("/api/auth/password", json={"current_password": "nope nope nope", "new_password": "another passphrase"})
    assert bad.status_code == 401


def test_delete_account_needs_password_and_removes_everything(client, llm):  # noqa: F811
    start_case(client, llm, "denial")
    assert client.request("DELETE", "/api/auth/account", json={"password": "wrong password!!"}).status_code == 401
    assert client.request("DELETE", "/api/auth/account", json={"password": PASSWORD}).status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    for table in ("users", "sessions", "uploads", "cases", "research_cases"):
        assert db_count(client, table) == 0, table
    assert login(fresh(client)).status_code == 401
    # Usage counts survive, unlinked from the deleted user.
    assert db_count(client, "events") > 0
    assert "sam@example.com" not in db_dump(client, "events")


# --- History -------------------------------------------------------------------------------


def test_history_lists_only_my_cases(client, llm, clock):  # noqa: F811
    a = start_case(client, llm, "denial")
    clock.advance(minutes=5)
    b = start_case(client, llm, "duplicate")
    cases = client.get("/api/cases").json()["cases"]
    assert [c["case_id"] for c in cases] == [b, a]  # newest first
    assert cases[1]["provider_name"] == "Riverside Medical Group"
    assert cases[1]["amount_due"] == "80.00" and cases[1]["flag_count"] == 2
    other = signup(fresh(client), "other@example.com")
    assert other.get("/api/cases").json() == {"cases": []}


# --- Research dataset and analytics --------------------------------------------------------


def test_research_record_with_consent_has_no_identifying_details(client, llm):  # noqa: F811
    start_case(client, llm, "denial")
    [row] = client.app.state.store.research_rows()
    data = row["data"]
    assert row["month"] == "2026-04"
    assert sorted(f["rule"] for f in data["flags"]) == ["balance_mismatch", "billed_after_denial"]
    assert [li["code"] for li in data["lines"]] == ["99213", "85025", "36415"]
    assert data["totals"]["patient_balance"] == "80.00" and data["eob"]["patient_responsibility"] == "25.00"
    text = json.dumps(row, default=str)
    for leak in ("Riverside", "Example Health", "5432", "C-2026-0001", "2026-03-04", "Complete blood", "sam@", "CO-50"):
        assert leak not in text, leak


def test_no_research_record_without_consent(pg_dsn, llm, clock):  # noqa: F811
    with make_client(pg_dsn, llm, clock) as c:
        signup(c, consent=False)
        start_case(c, llm, "denial")
        assert c.app.state.store.research_rows() == []


def test_withdrawing_consent_deletes_research_rows(client, llm):  # noqa: F811
    start_case(client, llm, "denial")
    assert len(client.app.state.store.research_rows()) == 1
    r = client.put("/api/auth/consent", json={"research_consent": False})
    assert r.json()["research_consent"] is False
    assert client.app.state.store.research_rows() == []


def test_usage_events_are_counted_without_content(client, llm):  # noqa: F811
    case_id = start_case(client, llm, "denial")
    client.post("/api/cases/{}/letter".format(case_id), json={"kind": "dispute", "patient": PATIENT})
    counts = client.app.state.store.event_counts()
    for name in ("signup", "upload", "case_created", "case_ready", "letter_created"):
        assert counts.get(name), name
    events = db_dump(client, "events")
    for leak in ("Riverside", "80.00", "Sam Example", "sam@example.com", case_id):
        assert leak not in events, leak


# --- Cross-site protection -----------------------------------------------------------------


def test_cross_site_posts_are_refused(client):  # noqa: F811
    r = client.post("/api/auth/logout", headers={"origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["detail"]["error"] == "bad_origin"
    assert client.post("/api/auth/logout", headers={"origin": "http://testserver"}).status_code == 204


def test_session_status_never_errors(client):  # noqa: F811
    assert client.get("/api/auth/session").json()["user"]["email"] == "sam@example.com"
    r = fresh(client).get("/api/auth/session")
    assert r.status_code == 200 and r.json() == {"user": None}
