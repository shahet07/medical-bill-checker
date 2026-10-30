import base64
import os
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.exceptions import InvalidTag

from billchecker.store import Store, hash_session, load_key, new_id

KEY = os.urandom(32)
S1, S2 = hash_session("session-one"), hash_session("session-two")
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
def store(tmp_path, clock):
    s = Store(tmp_path / "data", KEY, now=clock)
    yield s
    s.close()


def test_blob_round_trip_and_ciphertext_on_disk(store):
    up = store.add_upload(S1, "bill", "application/pdf", 1, SECRET)
    assert store.get_blob(up.upload_id) == SECRET
    on_disk = (store.blobs / up.upload_id).read_bytes()
    assert SECRET not in on_disk and b"00098765432" not in on_disk


def test_tampered_blob_fails_to_decrypt(store):
    up = store.add_upload(S1, "bill", "application/pdf", 1, SECRET)
    path = store.blobs / up.upload_id
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 1
    path.write_bytes(bytes(raw))
    with pytest.raises(InvalidTag):
        store.get_blob(up.upload_id)


def test_blob_cannot_be_swapped_under_another_id(store):
    a = store.add_upload(S1, "bill", "application/pdf", 1, SECRET)
    b = store.add_upload(S1, "bill", "application/pdf", 1, b"other")
    (store.blobs / b.upload_id).write_bytes((store.blobs / a.upload_id).read_bytes())
    with pytest.raises(InvalidTag):
        store.get_blob(b.upload_id)


def test_wrong_key_cannot_read(tmp_path, clock):
    s1 = Store(tmp_path / "d", KEY, now=clock)
    up = s1.add_upload(S1, "bill", "application/pdf", 1, SECRET)
    s2 = Store(tmp_path / "d", os.urandom(32), now=clock)
    with pytest.raises(InvalidTag):
        s2.get_blob(up.upload_id)


def test_index_holds_no_document_content(store):
    up = store.add_upload(S1, "bill", "application/pdf", 1, SECRET)
    case = store.add_case(S1, up.upload_id, None)
    store.put_result(case.case_id, {"bill": {"line": "Complete blood count", "charge": "40.00"}})
    index = (store.root / "index.sqlite3").read_bytes()
    assert b"Complete blood" not in index and b"40.00" not in index and b"session-one" not in index


def test_sessions_cannot_see_each_others_data(store):
    up = store.add_upload(S1, "bill", "application/pdf", 1, SECRET)
    case = store.add_case(S1, up.upload_id, None)
    assert store.get_upload(S2, up.upload_id) is None
    assert store.get_case(S2, case.case_id) is None
    assert store.delete_case(S2, case.case_id) is False
    assert store.get_case(S1, case.case_id) is not None


def test_status_updates_and_attempts(store):
    up = store.add_upload(S1, "bill", "application/pdf", 1, SECRET)
    case = store.add_case(S1, up.upload_id, None)
    store.set_status(case.case_id, "extracting", bump_attempts=True)
    store.set_status(case.case_id, "queued", "llm_unavailable")
    got = store.get_case(None, case.case_id)
    assert (got.status, got.error_code, got.attempts) == ("queued", "llm_unavailable", 1)


def test_delete_case_removes_case_and_upload_blobs(store):
    bill = store.add_upload(S1, "bill", "application/pdf", 1, SECRET)
    eob = store.add_upload(S1, "eob", "application/pdf", 1, b"eob")
    case = store.add_case(S1, bill.upload_id, eob.upload_id)
    store.put_result(case.case_id, {"x": 1})
    assert store.delete_case(S1, case.case_id)
    assert list(store.blobs.iterdir()) == []
    assert store.get_upload(S1, bill.upload_id) is None


def test_everything_expires_after_24_hours(store, clock):
    up = store.add_upload(S1, "bill", "application/pdf", 1, SECRET)
    case = store.add_case(S1, up.upload_id, None)
    store.put_result(case.case_id, {"x": 1})
    clock.advance(hours=23, minutes=59)
    assert store.get_case(S1, case.case_id) is not None
    assert store.cleanup() == 0
    clock.advance(minutes=2)
    assert store.get_case(S1, case.case_id) is None
    assert store.get_upload(S1, up.upload_id) is None
    assert store.cleanup() == 2
    assert list(store.blobs.iterdir()) == []


def test_upload_lives_as_long_as_its_case(store, clock):
    up = store.add_upload(S1, "bill", "application/pdf", 1, SECRET)
    clock.advance(hours=12)
    case = store.add_case(S1, up.upload_id, None)
    clock.advance(hours=13)  # 25h after upload, 13h after case creation
    store.cleanup()
    assert store.get_blob(up.upload_id) == SECRET
    assert store.get_case(S1, case.case_id) is not None


def test_cleanup_removes_old_orphans_but_not_fresh_ones(store, clock):
    old, fresh = store.blobs / new_id(), store.blobs / new_id()
    old.write_bytes(b"x")
    fresh.write_bytes(b"y")
    past = (clock() - timedelta(minutes=30)).timestamp()
    os.utime(old, (past, past))
    store.cleanup()
    assert not old.exists() and fresh.exists()


def test_bad_blob_ids_rejected(store):
    with pytest.raises(ValueError):
        store.get_blob("../index.sqlite3")


def test_load_key():
    assert load_key(base64.b64encode(KEY).decode()) == KEY
    for bad in (None, "", base64.b64encode(b"short").decode()):
        with pytest.raises(ValueError):
            load_key(bad)
