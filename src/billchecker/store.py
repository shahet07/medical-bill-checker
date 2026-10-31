"""PostgreSQL storage: users, login sessions, uploads, cases, and collected data.

Retention:
- Uploaded files (encrypted) are deleted 24 hours after upload.
- Cases (extracted data and results, encrypted) are kept 90 days, then deleted.
  Users can delete a case or their whole account at any time.
- Feedback, the research dataset (only with the user's consent), and usage
  events hold no names, providers, account numbers, dates, or files, and are
  kept for analysis. They use keyed one-way hashes instead of IDs, so they
  cannot be traced back to a user from the data alone.

Encryption: files and results are sealed with AES-256-GCM, one random nonce
each, with the row ID as associated data (a sealed value cannot be moved to
another row). Session tokens are stored only as SHA-256 hashes.
"""

import hashlib
import json
import os
import secrets
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

FILE_TTL = timedelta(hours=24)
CASE_TTL = timedelta(days=90)
SESSION_TTL = timedelta(days=14)
LOCKOUT_FAILURES = 10
LOCKOUT_TIME = timedelta(minutes=15)
NONCE_BYTES = 12
PACK_MAGIC = b"BCF1"

# Applied in order, once each. Never edit a released entry; append a new one.
MIGRATIONS = [
    """
    CREATE TABLE users (
        user_id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        research_consent BOOLEAN NOT NULL DEFAULT FALSE,
        failed_logins INTEGER NOT NULL DEFAULT 0,
        locked_until TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL,
        last_login_at TIMESTAMPTZ
    );
    CREATE TABLE sessions (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL
    );
    CREATE INDEX sessions_user ON sessions(user_id);
    CREATE TABLE uploads (
        upload_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        page_count INTEGER NOT NULL,
        data BYTEA,                      -- encrypted; NULL once the file is purged
        created_at TIMESTAMPTZ NOT NULL,
        files_expire_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL
    );
    CREATE INDEX uploads_user ON uploads(user_id);
    CREATE TABLE cases (
        case_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        bill_upload_id TEXT NOT NULL,
        eob_upload_ids JSONB NOT NULL,
        language TEXT NOT NULL DEFAULT 'en',
        status TEXT NOT NULL,
        error_code TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        result BYTEA,                    -- encrypted JSON
        created_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL
    );
    CREATE INDEX cases_user ON cases(user_id, created_at DESC);
    CREATE TABLE flag_feedback (
        feedback_key TEXT PRIMARY KEY,
        research_id TEXT,
        rule TEXT NOT NULL,
        confidence TEXT NOT NULL,
        verdict TEXT NOT NULL,
        model TEXT,
        updated_at TIMESTAMPTZ NOT NULL
    );
    CREATE TABLE survey (
        survey_key TEXT PRIMARY KEY,
        research_id TEXT,
        helpful INTEGER NOT NULL,
        most_useful TEXT NOT NULL,
        flag_count INTEGER NOT NULL,
        had_eob BOOLEAN NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    );
    CREATE TABLE research_cases (
        research_id TEXT PRIMARY KEY,
        month TEXT NOT NULL,             -- YYYY-MM only
        data JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    );
    CREATE TABLE events (
        event_id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        user_key TEXT,                   -- keyed hash; NULLed when the account is deleted
        props JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL
    );
    CREATE INDEX events_name_time ON events(name, created_at);
    """,
    # 2: dispute packets, document fingerprints, and the billing error radar.
    """
    ALTER TABLE users ADD COLUMN radar_consent BOOLEAN NOT NULL DEFAULT FALSE;
    ALTER TABLE uploads ADD COLUMN doc_sha256 JSONB NOT NULL DEFAULT '[]'::jsonb;
    CREATE TABLE packets (
        packet_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
        payload JSONB NOT NULL,          -- what the letter already states; no files
        signature TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    );
    CREATE INDEX packets_case ON packets(case_id);
    CREATE TABLE radar_reports (
        report_key TEXT PRIMARY KEY,     -- keyed hash of (case, flag)
        provider_key TEXT NOT NULL,      -- normalized provider name
        provider_name TEXT NOT NULL,
        rule TEXT NOT NULL,
        code TEXT,
        user_key TEXT NOT NULL,          -- keyed hash; counts distinct people
        case_key TEXT NOT NULL,          -- keyed hash; lets a case's reports be deleted
        confirmed BOOLEAN NOT NULL DEFAULT FALSE,
        month TEXT NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    );
    CREATE INDEX radar_provider ON radar_reports(provider_key);
    CREATE INDEX radar_user ON radar_reports(user_key);
    """,
]


class EmailTaken(Exception):
    pass


def pack_files(files: List[bytes]) -> bytes:
    """Several uploaded files -> one value (count, then length-prefixed files)."""
    out = [PACK_MAGIC, struct.pack(">I", len(files))]
    for f in files:
        out += [struct.pack(">Q", len(f)), f]
    return b"".join(out)


def unpack_files(blob: bytes) -> List[bytes]:
    if not blob.startswith(PACK_MAGIC):
        return [blob]
    (count,) = struct.unpack_from(">I", blob, 4)
    pos, files = 8, []
    for _ in range(count):
        (n,) = struct.unpack_from(">Q", blob, pos)
        files.append(blob[pos + 8 : pos + 8 + n])
        pos += 8 + n
    return files


def new_id() -> str:
    return secrets.token_hex(16)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def load_key(value: Optional[str]) -> bytes:
    """Parse a base64-encoded 32-byte key (e.g. from BILLCHECKER_KEY)."""
    import base64

    if not value:
        raise ValueError("encryption key is not set (BILLCHECKER_KEY)")
    key = base64.b64decode(value)
    if len(key) != 32:
        raise ValueError("encryption key must be 32 bytes, base64-encoded")
    return key


def is_id(value: str) -> bool:
    return len(value) == 32 and all(c in "0123456789abcdef" for c in value)


@dataclass(frozen=True)
class UserRow:
    user_id: str
    email: str
    password_hash: str
    research_consent: bool
    radar_consent: bool
    failed_logins: int
    locked_until: Optional[datetime]
    created_at: datetime


@dataclass(frozen=True)
class UploadRow:
    upload_id: str
    kind: str
    mime_type: str
    page_count: int
    expires_at: str


@dataclass(frozen=True)
class CaseRow:
    case_id: str
    user_id: str
    bill_upload_id: str
    eob_upload_ids: List[str]
    language: str
    status: str
    error_code: Optional[str]
    attempts: int
    created_at: str
    expires_at: str


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class Store:
    def __init__(
        self,
        dsn: str,
        key: bytes,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        pool_size: int = 10,
    ):
        self._aead = AESGCM(key)
        self._salt = hashlib.sha256(b"billchecker-pseudonym|" + key).digest()
        self._now = now
        self.file_ttl, self.case_ttl, self.session_ttl = FILE_TTL, CASE_TTL, SESSION_TTL
        self.pool = ConnectionPool(dsn, min_size=1, max_size=pool_size, kwargs={"autocommit": True}, open=True)
        self.migrate()

    def close(self) -> None:
        self.pool.close()

    def migrate(self) -> None:
        with self.pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(727001)")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)")
            done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            for version, sql in enumerate(MIGRATIONS, 1):
                if version not in done:
                    conn.execute(sql)
                    conn.execute("INSERT INTO schema_migrations VALUES (%s)", (version,))

    def _q(self, sql: str, args: tuple = ()) -> List[Dict[str, Any]]:
        with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            cur.execute(sql, args)
            return cur.fetchall() if cur.description else []

    def _one(self, sql: str, args: tuple = ()) -> Optional[Dict[str, Any]]:
        rows = self._q(sql, args)
        return rows[0] if rows else None

    # --- crypto and pseudonyms ------------------------------------------------------------

    def _seal(self, row_id: str, data: bytes) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, data, row_id.encode())

    def _open(self, row_id: str, sealed: Optional[bytes]) -> Optional[bytes]:
        if sealed is None:
            return None
        sealed = bytes(sealed)
        return self._aead.decrypt(sealed[:NONCE_BYTES], sealed[NONCE_BYTES:], row_id.encode())

    def pseudonym(self, *parts: str) -> str:
        """Keyed one-way hash: stable for joining collected data, not reversible."""
        return hashlib.sha256(self._salt + "|".join(parts).encode()).hexdigest()

    # --- users ------------------------------------------------------------------------------

    def _user(self, row: Optional[Dict[str, Any]]) -> Optional[UserRow]:
        if row is None:
            return None
        return UserRow(
            row["user_id"], row["email"], row["password_hash"], row["research_consent"], row["radar_consent"],
            row["failed_logins"], row["locked_until"], row["created_at"],
        )

    def create_user(self, email: str, password_hash: str, research_consent: bool) -> UserRow:
        import psycopg

        user_id = new_id()
        try:
            row = self._one(
                "INSERT INTO users (user_id, email, password_hash, research_consent, created_at) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING *",
                (user_id, email.lower(), password_hash, research_consent, self._now()),
            )
        except psycopg.errors.UniqueViolation:
            raise EmailTaken(email)
        return self._user(row)

    def get_user(self, user_id: str) -> Optional[UserRow]:
        return self._user(self._one("SELECT * FROM users WHERE user_id = %s", (user_id,)))

    def get_user_by_email(self, email: str) -> Optional[UserRow]:
        return self._user(self._one("SELECT * FROM users WHERE email = %s", (email.lower(),)))

    def is_locked(self, user: UserRow) -> bool:
        return user.locked_until is not None and user.locked_until > self._now()

    def record_login(self, user_id: str, success: bool) -> None:
        if success:
            self._q(
                "UPDATE users SET failed_logins = 0, locked_until = NULL, last_login_at = %s WHERE user_id = %s",
                (self._now(), user_id),
            )
        else:
            self._q(
                "UPDATE users SET failed_logins = failed_logins + 1, "
                "locked_until = CASE WHEN failed_logins + 1 >= %s THEN %s ELSE locked_until END WHERE user_id = %s",
                (LOCKOUT_FAILURES, self._now() + LOCKOUT_TIME, user_id),
            )

    def set_password(self, user_id: str, password_hash: str) -> None:
        self._q("UPDATE users SET password_hash = %s, failed_logins = 0, locked_until = NULL WHERE user_id = %s", (password_hash, user_id))

    def set_consent(self, user_id: str, consent: bool) -> None:
        self._q("UPDATE users SET research_consent = %s WHERE user_id = %s", (consent, user_id))

    def set_radar_consent(self, user_id: str, consent: bool) -> None:
        self._q("UPDATE users SET radar_consent = %s WHERE user_id = %s", (consent, user_id))
        if not consent:
            self._q("DELETE FROM radar_reports WHERE user_key = %s", (self.pseudonym("user", user_id),))

    def delete_user(self, user_id: str) -> None:
        """Deletes the account, its sessions, uploads, and cases (and their research rows).
        Usage events stay as counts but lose their link to the user."""
        for case in self._q("SELECT case_id FROM cases WHERE user_id = %s", (user_id,)):
            self._q("DELETE FROM research_cases WHERE research_id = %s", (self.pseudonym("case", case["case_id"]),))
        self._q("UPDATE events SET user_key = NULL WHERE user_key = %s", (self.pseudonym("user", user_id),))
        self._q("DELETE FROM radar_reports WHERE user_key = %s", (self.pseudonym("user", user_id),))
        self._q("DELETE FROM users WHERE user_id = %s", (user_id,))

    # --- sessions ---------------------------------------------------------------------------

    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = self._now()
        self._q(
            "INSERT INTO sessions VALUES (%s, %s, %s, %s)", (hash_token(token), user_id, now, now + self.session_ttl)
        )
        return token

    def session_user(self, token: str) -> Optional[UserRow]:
        row = self._one(
            "SELECT u.* FROM sessions s JOIN users u USING (user_id) WHERE s.token_hash = %s AND s.expires_at > %s",
            (hash_token(token), self._now()),
        )
        return self._user(row)

    def delete_session(self, token: str) -> None:
        self._q("DELETE FROM sessions WHERE token_hash = %s", (hash_token(token),))

    def delete_sessions(self, user_id: str, keep_token: Optional[str] = None) -> None:
        keep = hash_token(keep_token) if keep_token else ""
        self._q("DELETE FROM sessions WHERE user_id = %s AND token_hash <> %s", (user_id, keep))

    # --- uploads ----------------------------------------------------------------------------

    def add_upload(
        self, user_id: str, kind: str, mime_type: str, page_count: int, data: bytes, doc_sha256: Optional[List[str]] = None
    ) -> UploadRow:
        """doc_sha256: fingerprint of each uploaded file, kept after the file itself is purged."""
        upload_id = new_id()
        now = self._now()
        self._q(
            "INSERT INTO uploads (upload_id, user_id, kind, mime_type, page_count, data, created_at, files_expire_at, "
            "expires_at, doc_sha256) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (upload_id, user_id, kind, mime_type, page_count, self._seal(upload_id, data), now, now + self.file_ttl,
             now + self.file_ttl, Jsonb(list(doc_sha256 or []))),
        )
        return UploadRow(upload_id, kind, mime_type, page_count, _iso(now + self.file_ttl))

    def get_upload(self, user_id: str, upload_id: str) -> Optional[UploadRow]:
        if not is_id(upload_id):
            return None
        row = self._one(
            "SELECT * FROM uploads WHERE upload_id = %s AND user_id = %s AND files_expire_at > %s AND data IS NOT NULL",
            (upload_id, user_id, self._now()),
        )
        if row is None:
            return None
        return UploadRow(row["upload_id"], row["kind"], row["mime_type"], row["page_count"], _iso(row["files_expire_at"]))

    def get_upload_hashes(self, upload_id: str) -> List[str]:
        row = self._one("SELECT doc_sha256 FROM uploads WHERE upload_id = %s", (upload_id,))
        return list(row["doc_sha256"]) if row else []

    def get_upload_data(self, upload_id: str) -> Optional[bytes]:
        row = self._one("SELECT data FROM uploads WHERE upload_id = %s AND files_expire_at > %s", (upload_id, self._now()))
        return self._open(upload_id, row["data"]) if row else None

    # --- cases ------------------------------------------------------------------------------

    def _case(self, row: Optional[Dict[str, Any]]) -> Optional[CaseRow]:
        if row is None:
            return None
        return CaseRow(
            row["case_id"], row["user_id"], row["bill_upload_id"], list(row["eob_upload_ids"]), row["language"],
            row["status"], row["error_code"], row["attempts"], _iso(row["created_at"]), _iso(row["expires_at"]),
        )

    def add_case(self, user_id: str, bill_upload_id: str, eob_upload_ids: List[str], language: str = "en") -> CaseRow:
        case_id = new_id()
        now = self._now()
        row = self._one(
            "INSERT INTO cases (case_id, user_id, bill_upload_id, eob_upload_ids, language, status, created_at, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, 'queued', %s, %s) RETURNING *",
            (case_id, user_id, bill_upload_id, Jsonb(list(eob_upload_ids)), language, now, now + self.case_ttl),
        )
        # Uploads stay as rows for the life of the case; their file data is still purged after 24h.
        self._q(
            "UPDATE uploads SET expires_at = %s WHERE upload_id = ANY(%s)",
            (now + self.case_ttl, [bill_upload_id] + list(eob_upload_ids)),
        )
        return self._case(row)

    def get_case(self, user_id: Optional[str], case_id: str) -> Optional[CaseRow]:
        """user_id=None is for the worker, which already owns the case."""
        if not is_id(case_id):
            return None
        sql, args = "SELECT * FROM cases WHERE case_id = %s AND expires_at > %s", [case_id, self._now()]
        if user_id is not None:
            sql += " AND user_id = %s"
            args.append(user_id)
        return self._case(self._one(sql, tuple(args)))

    def list_cases(self, user_id: str, limit: int = 100) -> List[CaseRow]:
        rows = self._q(
            "SELECT * FROM cases WHERE user_id = %s AND expires_at > %s ORDER BY created_at DESC LIMIT %s",
            (user_id, self._now(), limit),
        )
        return [self._case(r) for r in rows]

    def set_status(self, case_id: str, status: str, error_code: Optional[str] = None, bump_attempts: bool = False) -> None:
        self._q(
            "UPDATE cases SET status = %s, error_code = %s, attempts = attempts + %s WHERE case_id = %s",
            (status, error_code, 1 if bump_attempts else 0, case_id),
        )

    def set_language(self, case_id: str, language: str) -> None:
        self._q("UPDATE cases SET language = %s WHERE case_id = %s", (language, case_id))

    def put_result(self, case_id: str, result: Dict[str, Any]) -> None:
        self._q("UPDATE cases SET result = %s WHERE case_id = %s", (self._seal(case_id, json.dumps(result).encode()), case_id))

    def get_result(self, case_id: str) -> Optional[Dict[str, Any]]:
        row = self._one("SELECT result FROM cases WHERE case_id = %s", (case_id,))
        data = self._open(case_id, row["result"]) if row else None
        return json.loads(data) if data is not None else None

    def delete_case(self, user_id: str, case_id: str) -> bool:
        case = self.get_case(user_id, case_id)
        if case is None:
            return False
        self._q("DELETE FROM uploads WHERE upload_id = ANY(%s)", ([case.bill_upload_id] + case.eob_upload_ids,))
        self._q("DELETE FROM research_cases WHERE research_id = %s", (self.pseudonym("case", case_id),))
        self.delete_radar_case(case_id)
        self._q("DELETE FROM cases WHERE case_id = %s", (case_id,))  # packets go with it
        return True

    # --- dispute packets --------------------------------------------------------------------

    def put_packet(self, packet_id: str, case_id: str, payload: Dict[str, Any], signature: str) -> None:
        self._q(
            "INSERT INTO packets VALUES (%s, %s, %s, %s, %s)", (packet_id, case_id, Jsonb(payload), signature, self._now())
        )

    def get_packet(self, packet_id: str) -> Optional[Dict[str, Any]]:
        """A packet is verifiable while its case exists (90 days unless deleted)."""
        return self._one(
            "SELECT p.payload, p.signature, p.created_at FROM packets p JOIN cases c USING (case_id) "
            "WHERE p.packet_id = %s AND c.expires_at > %s",
            (packet_id, self._now()),
        )

    # --- billing error radar ----------------------------------------------------------------

    def put_radar_reports(self, case_id: str, user_id: str, provider_key: str, provider_name: str, items: List[Dict[str, Any]]) -> None:
        """Replace this case's reports. items: {flag_id, rule, code}."""
        case_key, user_key = self.pseudonym("case", case_id), self.pseudonym("user", user_id)
        now = self._now()
        with self.pool.connection() as conn, conn.transaction():
            confirmed = {
                r[0]
                for r in conn.execute(
                    "SELECT report_key FROM radar_reports WHERE case_key = %s AND confirmed", (case_key,)
                )
            }
            conn.execute("DELETE FROM radar_reports WHERE case_key = %s", (case_key,))
            for item in items:
                key = self.pseudonym("radar", case_id, item["flag_id"])
                conn.execute(
                    "INSERT INTO radar_reports VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (key, provider_key, provider_name, item["rule"], item.get("code"), user_key, case_key,
                     key in confirmed, now.strftime("%Y-%m"), now),
                )

    def confirm_radar_report(self, case_id: str, flag_id: str, confirmed: bool) -> None:
        self._q(
            "UPDATE radar_reports SET confirmed = %s, updated_at = %s WHERE report_key = %s",
            (confirmed, self._now(), self.pseudonym("radar", case_id, flag_id)),
        )

    def delete_radar_case(self, case_id: str) -> None:
        self._q("DELETE FROM radar_reports WHERE case_key = %s", (self.pseudonym("case", case_id),))

    def radar_patterns(self, provider_key: str, k: int) -> List[Dict[str, Any]]:
        """Patterns at one provider reported by at least k different people."""
        return self._q(
            "SELECT rule, code, count(DISTINCT user_key) AS users, "
            "count(DISTINCT user_key) FILTER (WHERE confirmed) AS confirmed_users, max(month) AS last_month "
            "FROM radar_reports WHERE provider_key = %s GROUP BY rule, code HAVING count(DISTINCT user_key) >= %s "
            "ORDER BY users DESC, rule, code",
            (provider_key, k),
        )

    def radar_providers(self, query: str, k: int, limit: int = 20) -> List[Dict[str, Any]]:
        """Providers with at least one pattern reported by k or more people, matching the search text."""
        return self._q(
            "SELECT provider_key, mode() WITHIN GROUP (ORDER BY provider_name) AS provider_name, count(*) AS patterns "
            "FROM (SELECT provider_key, provider_name, rule, coalesce(code, '') AS code FROM radar_reports "
            "      GROUP BY provider_key, provider_name, rule, coalesce(code, '')) AS named "
            # coalesce: rules without a code (e.g. balance mismatch) must still match.
            "WHERE provider_key LIKE %s AND (provider_key, rule, code) IN ("
            "  SELECT provider_key, rule, coalesce(code, '') FROM radar_reports GROUP BY provider_key, rule, coalesce(code, '') "
            "  HAVING count(DISTINCT user_key) >= %s) "
            "GROUP BY provider_key ORDER BY patterns DESC, provider_key LIMIT %s",
            ("%" + query + "%", k, limit),
        )

    # --- collected data ---------------------------------------------------------------------

    def record_flag_feedback(self, case_id: str, flag_id: str, rule: str, confidence: str, verdict: str, model: Optional[str]) -> None:
        self._q(
            "INSERT INTO flag_feedback VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (feedback_key) DO UPDATE "
            "SET verdict = EXCLUDED.verdict, updated_at = EXCLUDED.updated_at",
            (self.pseudonym("flag", case_id, flag_id), self.pseudonym("case", case_id), rule, confidence, verdict, model, self._now()),
        )

    def record_survey(self, case_id: str, helpful: int, most_useful: str, flag_count: int, had_eob: bool) -> None:
        self._q(
            "INSERT INTO survey VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (survey_key) DO UPDATE "
            "SET helpful = EXCLUDED.helpful, most_useful = EXCLUDED.most_useful, updated_at = EXCLUDED.updated_at",
            (self.pseudonym("survey", case_id), self.pseudonym("case", case_id), helpful, most_useful, flag_count, had_eob, self._now()),
        )

    def put_research(self, case_id: str, data: Dict[str, Any]) -> None:
        now = self._now()
        self._q(
            "INSERT INTO research_cases VALUES (%s, %s, %s, %s) ON CONFLICT (research_id) DO UPDATE "
            "SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at",
            (self.pseudonym("case", case_id), now.strftime("%Y-%m"), Jsonb(data), now),
        )

    def delete_research(self, case_id: str) -> None:
        self._q("DELETE FROM research_cases WHERE research_id = %s", (self.pseudonym("case", case_id),))

    def record_event(self, name: str, user_id: Optional[str] = None, **props: Any) -> None:
        user_key = self.pseudonym("user", user_id) if user_id else None
        self._q("INSERT INTO events (name, user_key, props, created_at) VALUES (%s, %s, %s, %s)", (name, user_key, Jsonb(props), self._now()))

    def feedback_rows(self) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "flags": self._q("SELECT rule, confidence, verdict, model, research_id FROM flag_feedback"),
            "survey": self._q("SELECT helpful, most_useful, flag_count, had_eob, research_id FROM survey"),
        }

    def research_rows(self) -> List[Dict[str, Any]]:
        return self._q("SELECT research_id, month, data FROM research_cases ORDER BY month, research_id")

    def event_counts(self, since: Optional[datetime] = None) -> Dict[str, int]:
        rows = self._q(
            "SELECT name, count(*) AS n FROM events WHERE created_at >= %s GROUP BY name ORDER BY name",
            (since or datetime(1970, 1, 1, tzinfo=timezone.utc),),
        )
        return {r["name"]: r["n"] for r in rows}

    # --- expiry -----------------------------------------------------------------------------

    def cleanup(self) -> Dict[str, int]:
        """Purge file data after 24h, delete cases after 90 days, drop expired sessions."""
        now = self._now()
        counts = {}
        with self.pool.connection() as conn:
            counts["files_purged"] = conn.execute(
                "UPDATE uploads SET data = NULL WHERE files_expire_at <= %s AND data IS NOT NULL", (now,)
            ).rowcount
            counts["uploads_deleted"] = conn.execute("DELETE FROM uploads WHERE expires_at <= %s", (now,)).rowcount
            counts["cases_deleted"] = conn.execute("DELETE FROM cases WHERE expires_at <= %s", (now,)).rowcount
            counts["sessions_deleted"] = conn.execute("DELETE FROM sessions WHERE expires_at <= %s", (now,)).rowcount
        return counts
