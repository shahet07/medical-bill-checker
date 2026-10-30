import os
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from cryptography.exceptions import InvalidTag

from billchecker.store import EmailTaken, Store, hash_token, load_key, pack_files, unpack_files

KEY = os.urandom(32)
SECRET = b"Complete blood count $40.00 account 00098765432"


class Clock:
    def __init__(self):
        self.t = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(pg_dsn, clock):
    s = Store(pg_dsn, KEY, now=clock)
    yield s
    s.close()


@pytest.fixture
def alice(store):
    return store.create_user("Alice@Example.com", "hash-a", research_consent=True)


@pytest.fixture
def bob(store):
    return store.create_user("bob@example.com", "hash-b", research_consent=False)


def raw(store, sql, args=()):
    with store.pool.connection() as conn:
        cur = conn.execute(sql, args)
        return cur.fetchall() if cur.description else []


# --- Users and sessions -------------------------------------------------------------------


def test_users_are_unique_by_lowercased_email(store, alice):
    assert alice.email == "alice@example.com"
    assert store.get_user_by_email("ALICE@example.com").user_id == alice.user_id
    with pytest.raises(EmailTaken):
        store.create_user("alice@EXAMPLE.com", "x", False)


def test_sessions_stored_as_hashes_and_expire(store, alice, clock):
    token = store.create_session(alice.user_id)
    assert store.session_user(token).user_id == alice.user_id
    assert raw(store, "SELECT token_hash FROM sessions") == [(hash_token(token),)]
    clock.advance(days=14, seconds=1)
    assert store.session_user(token) is None
    assert store.cleanup()["sessions_deleted"] == 1


def test_delete_sessions_keeps_current(store, alice):
    a, b = store.create_session(alice.user_id), store.create_session(alice.user_id)
    store.delete_sessions(alice.user_id, keep_token=a)
    assert store.session_user(a) is not None and store.session_user(b) is None


def test_lockout_after_ten_failures(store, alice, clock):
    for _ in range(9):
        store.record_login(alice.user_id, success=False)
    assert not store.is_locked(store.get_user(alice.user_id))
    store.record_login(alice.user_id, success=False)
    assert store.is_locked(store.get_user(alice.user_id))
    clock.advance(minutes=16)
    assert not store.is_locked(store.get_user(alice.user_id))
    store.record_login(alice.user_id, success=True)
    assert store.get_user(alice.user_id).failed_logins == 0


# --- Encryption at rest ----------------------------------------------------------------


def test_files_and_results_are_encrypted_in_the_database(store, alice):
    up = store.add_upload(alice.user_id, "bill", "application/pdf", 1, SECRET)
    case = store.add_case(alice.user_id, up.upload_id, [])
    store.put_result(case.case_id, {"bill": {"provider_name": "Riverside Medical Group"}})
    assert store.get_upload_data(up.upload_id) == SECRET
    assert store.get_result(case.case_id)["bill"]["provider_name"] == "Riverside Medical Group"
    [(data,)] = raw(store, "SELECT data FROM uploads")
    [(result,)] = raw(store, "SELECT result FROM cases")
    assert SECRET not in bytes(data) and b"Riverside" not in bytes(result)


def test_encrypted_value_cannot_be_moved_to_another_row(store, alice):
    a = store.add_upload(alice.user_id, "bill", "application/pdf", 1, SECRET)
    b = store.add_upload(alice.user_id, "bill", "application/pdf", 1, b"other")
    raw(store, "UPDATE uploads SET data = (SELECT data FROM uploads WHERE upload_id = %s) WHERE upload_id = %s", (a.upload_id, b.upload_id))
    with pytest.raises(InvalidTag):
        store.get_upload_data(b.upload_id)


def test_wrong_key_cannot_read(pg_dsn, store, alice, clock):
    up = store.add_upload(alice.user_id, "bill", "application/pdf", 1, SECRET)
    other = Store(pg_dsn, os.urandom(32), now=clock)
    try:
        with pytest.raises(InvalidTag):
            other.get_upload_data(up.upload_id)
    finally:
        other.close()


# --- Ownership --------------------------------------------------------------------------


def test_users_cannot_see_each_others_data(store, alice, bob):
    up = store.add_upload(alice.user_id, "bill", "application/pdf", 1, SECRET)
    case = store.add_case(alice.user_id, up.upload_id, [])
    assert store.get_upload(bob.user_id, up.upload_id) is None
    assert store.get_case(bob.user_id, case.case_id) is None
    assert store.list_cases(bob.user_id) == []
    assert store.delete_case(bob.user_id, case.case_id) is False
    assert [c.case_id for c in store.list_cases(alice.user_id)] == [case.case_id]


def test_bad_ids_return_nothing(store, alice):
    assert store.get_case(alice.user_id, "../etc") is None
    assert store.get_upload(alice.user_id, "x" * 32) is None


# --- Retention ---------------------------------------------------------------------------


def test_files_purged_after_24h_cases_kept_90_days(store, alice, clock):
    up = store.add_upload(alice.user_id, "bill", "application/pdf", 1, SECRET)
    case = store.add_case(alice.user_id, up.upload_id, [])
    store.put_result(case.case_id, {"x": 1})
    clock.advance(hours=24, seconds=1)
    assert store.cleanup()["files_purged"] == 1
    assert store.get_upload_data(up.upload_id) is None
    assert raw(store, "SELECT data FROM uploads") == [(None,)]
    assert store.get_result(case.case_id) == {"x": 1}  # results still there
    clock.advance(days=88, hours=23)  # 89 days 23 hours after creation
    assert store.get_case(alice.user_id, case.case_id) is not None
    clock.advance(hours=2)
    assert store.get_case(alice.user_id, case.case_id) is None
    counts = store.cleanup()
    assert counts["cases_deleted"] == 1 and counts["uploads_deleted"] == 1
    assert raw(store, "SELECT count(*) FROM cases") == [(0,)]


def test_upload_never_used_is_deleted_after_24h(store, alice, clock):
    store.add_upload(alice.user_id, "bill", "application/pdf", 1, SECRET)
    clock.advance(hours=25)
    assert store.cleanup()["uploads_deleted"] == 1


def test_delete_case_removes_uploads_and_research(store, alice):
    bill = store.add_upload(alice.user_id, "bill", "application/pdf", 1, SECRET)
    eob = store.add_upload(alice.user_id, "eob", "application/pdf", 1, b"eob")
    case = store.add_case(alice.user_id, bill.upload_id, [eob.upload_id])
    store.put_research(case.case_id, {"flags": []})
    assert store.delete_case(alice.user_id, case.case_id)
    assert raw(store, "SELECT count(*) FROM uploads") == [(0,)]
    assert store.research_rows() == []


def test_delete_user_removes_everything_but_keeps_unlinked_counts(store, alice, bob):
    up = store.add_upload(alice.user_id, "bill", "application/pdf", 1, SECRET)
    case = store.add_case(alice.user_id, up.upload_id, [])
    store.put_research(case.case_id, {"flags": []})
    store.create_session(alice.user_id)
    store.record_event("upload", alice.user_id)
    store.record_event("upload", bob.user_id)
    store.delete_user(alice.user_id)
    for table in ("users", "sessions", "uploads", "cases", "research_cases"):
        n = raw(store, "SELECT count(*) FROM {} ".format(table) + ("WHERE user_id = %s" if table in ("users", "sessions", "uploads", "cases") else ""),
                (alice.user_id,) if table != "research_cases" else ())
        assert n == [(0,)], table
    assert store.event_counts() == {"upload": 2}
    assert raw(store, "SELECT count(*) FROM events WHERE user_key IS NULL") == [(1,)]


# --- Collected data ------------------------------------------------------------------------


def test_collected_data_has_no_ids_or_content(store, alice):
    up = store.add_upload(alice.user_id, "bill", "application/pdf", 1, SECRET)
    case = store.add_case(alice.user_id, up.upload_id, [])
    store.record_flag_feedback(case.case_id, "duplicate_line:bill.L2,bill.L3", "duplicate_line", "medium", "correct", "m")
    store.record_survey(case.case_id, 4, "letter", 1, False)
    store.put_research(case.case_id, {"flags": [{"rule": "duplicate_line"}]})
    store.record_event("upload", alice.user_id, kind="bill")
    dump = repr(raw(store, "SELECT * FROM flag_feedback") + raw(store, "SELECT * FROM survey")
                + raw(store, "SELECT * FROM research_cases") + raw(store, "SELECT * FROM events"))
    for leak in (case.case_id, alice.user_id, "alice", "bill.L2"):
        assert leak not in dump
    # Feedback and research join through the same one-way key.
    [fb] = store.feedback_rows()["flags"]
    [rs] = store.research_rows()
    assert fb["research_id"] == rs["research_id"] and rs["month"] == "2026-04"


def test_feedback_upserts(store, alice):
    up = store.add_upload(alice.user_id, "bill", "application/pdf", 1, SECRET)
    case = store.add_case(alice.user_id, up.upload_id, [])
    store.record_flag_feedback(case.case_id, "f1", "duplicate_line", "medium", "incorrect", None)
    store.record_flag_feedback(case.case_id, "f1", "duplicate_line", "medium", "correct", None)
    assert [r["verdict"] for r in store.feedback_rows()["flags"]] == ["correct"]


def test_event_counts_since(store, alice, clock):
    store.record_event("login", alice.user_id)
    clock.advance(days=2)
    store.record_event("login", alice.user_id)
    assert store.event_counts() == {"login": 2}
    assert store.event_counts(since=clock() - timedelta(days=1)) == {"login": 1}


def test_migrations_are_idempotent(pg_dsn, store, clock):
    again = Store(pg_dsn, KEY, now=clock)
    again.close()
    assert raw(store, "SELECT version FROM schema_migrations") == [(1,)]


# --- Helpers ----------------------------------------------------------------------------


def test_pack_unpack_files():
    files = [b"", b"one", bytes(range(256)) * 10]
    assert unpack_files(pack_files(files)) == files
    assert unpack_files(b"%PDF-plain single file") == [b"%PDF-plain single file"]


def test_load_key():
    import base64

    assert load_key(base64.b64encode(KEY).decode()) == KEY
    for bad in (None, "", base64.b64encode(b"short").decode()):
        with pytest.raises(ValueError):
            load_key(bad)
