import base64
import json
import os

import pytest

from billchecker import admin
from billchecker.auth import login
from billchecker.store import Store

KEY = os.urandom(32)


@pytest.fixture
def env(pg_dsn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    monkeypatch.setenv("BILLCHECKER_KEY", base64.b64encode(KEY).decode())
    store = Store(pg_dsn, KEY)
    yield store
    store.close()


def test_stats_runs_and_prints_no_content(env, capsys):
    user = env.create_user("a@example.com", "h", True)
    env.record_event("upload", user.user_id)
    admin.main(["stats"])
    out = capsys.readouterr().out
    assert "Users: 1" in out and "upload" in out and "a@example.com" not in out


def test_reset_password_logs_out_and_lets_user_in(env, capsys):
    user = env.create_user("a@example.com", "h", False)
    token = env.create_session(user.user_id)
    admin.main(["reset-password", "A@example.com"])
    temp = capsys.readouterr().out.split(": ", 1)[1].split()[0]
    assert env.session_user(token) is None
    assert login(env, "a@example.com", temp).user_id == user.user_id


def test_delete_user_needs_yes(env):
    env.create_user("a@example.com", "h", False)
    with pytest.raises(SystemExit):
        admin.main(["delete-user", "a@example.com"])
    assert env.get_user_by_email("a@example.com") is not None
    admin.main(["delete-user", "a@example.com", "--yes"])
    assert env.get_user_by_email("a@example.com") is None


def test_export_research(env, tmp_path):
    user = env.create_user("a@example.com", "h", True)
    up = env.add_upload(user.user_id, "bill", "application/pdf", 1, b"x")
    case = env.add_case(user.user_id, up.upload_id, [])
    env.put_research(case.case_id, {"flags": [{"rule": "duplicate_line"}]})
    out = tmp_path / "r.jsonl"
    admin.main(["export-research", str(out)])
    [row] = [json.loads(line) for line in out.read_text().splitlines()]
    assert row["flags"] == [{"rule": "duplicate_line"}] and "research_id" in row and case.case_id not in out.read_text()
