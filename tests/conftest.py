import json
import os
import secrets
from typing import Any, Dict, List, Union

import psycopg
import pytest
from argon2 import PasswordHasher

from billchecker import auth

from billchecker.llm import LLMResponse
from synthetic import build_files


class FakeLLM:
    """Replays scripted responses and records every call. No network, no cost."""

    def __init__(self, *responses: Union[str, Dict, LLMResponse]):
        self.responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def generate(self, system, content, schema):
        self.calls.append({"system": system, "content": content, "schema": schema})
        resp = self.responses.pop(0)
        if isinstance(resp, LLMResponse):
            return resp
        if isinstance(resp, dict):
            resp = json.dumps(resp)
        return LLMResponse(text=resp, stop_reason="end_turn")


@pytest.fixture(scope="session")
def fixture_files(tmp_path_factory):
    return build_files(tmp_path_factory.mktemp("fixtures"))


TEST_DB = os.environ.get("BILLCHECKER_TEST_DATABASE_URL", "postgresql://billchecker@127.0.0.1:54329/billchecker_test")


@pytest.fixture
def pg_dsn():
    """A fresh, empty schema per test in the test database, dropped afterwards."""
    try:
        admin = psycopg.connect(TEST_DB, autocommit=True)
    except psycopg.OperationalError:
        pytest.exit("Test database not reachable at {}. Start it with: scripts/dev_db.sh start".format(TEST_DB), returncode=2)
    schema = "t_" + secrets.token_hex(6)
    admin.execute("CREATE SCHEMA " + schema)
    yield TEST_DB + ("&" if "?" in TEST_DB else "?") + "options=-csearch_path%3D" + schema
    admin.execute("DROP SCHEMA {} CASCADE".format(schema))
    admin.close()


@pytest.fixture(autouse=True)
def fast_password_hashing(monkeypatch):
    # Production uses Argon2id defaults; tests only need it to be correct, not slow.
    monkeypatch.setattr(auth, "_hasher", PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
