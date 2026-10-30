"""Encrypted, expiring storage for uploads and case results.

- Document bytes and results are encrypted with AES-256-GCM, one random
  nonce per blob, with the blob ID as associated data (a blob cannot be
  swapped under another ID). Files are named by random ID only.
- A small SQLite index holds IDs, status, and expiry. It never holds
  document content or amounts. Session tokens are stored as SHA-256 hashes.
- Everything expires (default 24 hours); cleanup() deletes expired rows and
  their blobs, plus any orphaned blob files.
"""

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import struct
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TTL = timedelta(hours=24)
ORPHAN_GRACE = timedelta(minutes=10)
NONCE_BYTES = 12
SCHEMA_VERSION = 2
PACK_MAGIC = b"BCF1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
    upload_id TEXT PRIMARY KEY,
    session_hash TEXT NOT NULL,
    kind TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    session_hash TEXT NOT NULL,
    bill_upload_id TEXT NOT NULL,
    eob_upload_ids TEXT NOT NULL,  -- JSON list of upload IDs
    status TEXT NOT NULL,
    error_code TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
-- Validation feedback. No document content, no session, no case ID: only a
-- one-way key for de-duplication, so these rows can outlive the 24h expiry.
CREATE TABLE IF NOT EXISTS flag_feedback (
    feedback_key TEXT PRIMARY KEY,
    rule TEXT NOT NULL,
    confidence TEXT NOT NULL,
    verdict TEXT NOT NULL,
    model TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS survey (
    survey_key TEXT PRIMARY KEY,
    helpful INTEGER NOT NULL,
    most_useful TEXT NOT NULL,
    flag_count INTEGER NOT NULL,
    had_eob INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def pack_files(files: List[bytes]) -> bytes:
    """Several uploaded files -> one blob (count, then length-prefixed files)."""
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


def hash_session(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def load_key(value: Optional[str]) -> bytes:
    """Parse a base64-encoded 32-byte key (e.g. from BILLCHECKER_KEY)."""
    if not value:
        raise ValueError("encryption key is not set (BILLCHECKER_KEY)")
    key = base64.b64decode(value)
    if len(key) != 32:
        raise ValueError("encryption key must be 32 bytes, base64-encoded")
    return key


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


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
    bill_upload_id: str
    eob_upload_ids: List[str]
    status: str
    error_code: Optional[str]
    attempts: int
    expires_at: str


class Store:
    def __init__(
        self,
        root: Path,
        key: bytes,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        ttl: timedelta = TTL,
    ):
        self.root = Path(root)
        self.blobs = self.root / "blobs"
        self.blobs.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self._aead = AESGCM(key)
        self._feedback_salt = hashlib.sha256(b"billchecker-feedback|" + key).digest()
        self._now = now
        self.ttl = ttl
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.root / "index.sqlite3"), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        if self._db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            # Everything stored is temporary, so an old index is simply replaced;
            # its blobs become orphans and are removed by cleanup().
            self._db.executescript("DROP TABLE IF EXISTS cases; DROP TABLE IF EXISTS uploads;")
            self._db.execute("PRAGMA user_version = {}".format(SCHEMA_VERSION))
        self._db.executescript(SCHEMA)

    # --- blobs ------------------------------------------------------------------------

    def _blob_path(self, blob_id: str) -> Path:
        if not all(c in "0123456789abcdef" for c in blob_id) or len(blob_id) != 32:
            raise ValueError("bad blob id")
        return self.blobs / blob_id

    def put_blob(self, blob_id: str, data: bytes) -> None:
        nonce = os.urandom(NONCE_BYTES)
        sealed = nonce + self._aead.encrypt(nonce, data, blob_id.encode())
        path = self._blob_path(blob_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(sealed)
        os.chmod(tmp, 0o600)
        tmp.replace(path)

    def get_blob(self, blob_id: str) -> Optional[bytes]:
        path = self._blob_path(blob_id)
        if not path.exists():
            return None
        sealed = path.read_bytes()
        return self._aead.decrypt(sealed[:NONCE_BYTES], sealed[NONCE_BYTES:], blob_id.encode())

    def delete_blob(self, blob_id: str) -> None:
        try:
            self._blob_path(blob_id).unlink()
        except FileNotFoundError:
            pass

    # --- uploads ----------------------------------------------------------------------

    def add_upload(self, session_hash: str, kind: str, mime_type: str, page_count: int, data: bytes) -> UploadRow:
        upload_id = new_id()
        now = self._now()
        self.put_blob(upload_id, data)
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO uploads VALUES (?, ?, ?, ?, ?, ?, ?)",
                (upload_id, session_hash, kind, mime_type, page_count, _iso(now), _iso(now + self.ttl)),
            )
        return UploadRow(upload_id, kind, mime_type, page_count, _iso(now + self.ttl))

    def get_upload(self, session_hash: str, upload_id: str) -> Optional[UploadRow]:
        row = self._one(
            "SELECT * FROM uploads WHERE upload_id = ? AND session_hash = ? AND expires_at > ?",
            (upload_id, session_hash, _iso(self._now())),
        )
        if row is None:
            return None
        return UploadRow(row["upload_id"], row["kind"], row["mime_type"], row["page_count"], row["expires_at"])

    # --- cases ------------------------------------------------------------------------

    def add_case(self, session_hash: str, bill_upload_id: str, eob_upload_ids: List[str]) -> CaseRow:
        case_id = new_id()
        now = self._now()
        expires = _iso(now + self.ttl)
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO cases VALUES (?, ?, ?, ?, 'queued', NULL, 0, ?, ?)",
                (case_id, session_hash, bill_upload_id, json.dumps(eob_upload_ids), _iso(now), expires),
            )
            # The uploads now live as long as the case that uses them.
            for upload_id in [bill_upload_id] + list(eob_upload_ids):
                self._db.execute("UPDATE uploads SET expires_at = ? WHERE upload_id = ?", (expires, upload_id))
        return CaseRow(case_id, bill_upload_id, list(eob_upload_ids), "queued", None, 0, expires)

    def get_case(self, session_hash: Optional[str], case_id: str) -> Optional[CaseRow]:
        """session_hash=None is for the worker, which already owns the case."""
        sql = "SELECT * FROM cases WHERE case_id = ? AND expires_at > ?"
        args: List[Any] = [case_id, _iso(self._now())]
        if session_hash is not None:
            sql += " AND session_hash = ?"
            args.append(session_hash)
        row = self._one(sql, tuple(args))
        if row is None:
            return None
        return CaseRow(
            row["case_id"],
            row["bill_upload_id"],
            json.loads(row["eob_upload_ids"]),
            row["status"],
            row["error_code"],
            row["attempts"],
            row["expires_at"],
        )

    def set_status(self, case_id: str, status: str, error_code: Optional[str] = None, bump_attempts: bool = False) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE cases SET status = ?, error_code = ?, attempts = attempts + ? WHERE case_id = ?",
                (status, error_code, 1 if bump_attempts else 0, case_id),
            )

    def put_result(self, case_id: str, result: Dict[str, Any]) -> None:
        self.put_blob(case_id, json.dumps(result).encode())

    def get_result(self, case_id: str) -> Optional[Dict[str, Any]]:
        data = self.get_blob(case_id)
        return json.loads(data) if data is not None else None

    # --- feedback ---------------------------------------------------------------------

    def _feedback_key(self, *parts: str) -> str:
        # Keyed hash so the stored key cannot be linked back to a case ID.
        return hashlib.sha256(self._feedback_salt + "|".join(parts).encode()).hexdigest()

    def record_flag_feedback(self, case_id: str, flag_id: str, rule: str, confidence: str, verdict: str, model: Optional[str]) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO flag_feedback VALUES (?, ?, ?, ?, ?, ?)",
                (self._feedback_key("flag", case_id, flag_id), rule, confidence, verdict, model, _iso(self._now())),
            )

    def record_survey(self, case_id: str, helpful: int, most_useful: str, flag_count: int, had_eob: bool) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO survey VALUES (?, ?, ?, ?, ?, ?)",
                (self._feedback_key("survey", case_id), helpful, most_useful, flag_count, int(had_eob), _iso(self._now())),
            )

    def feedback_rows(self) -> Dict[str, List[Dict[str, Any]]]:
        with self._lock:
            return {
                "flags": [dict(r) for r in self._db.execute("SELECT rule, confidence, verdict, model FROM flag_feedback")],
                "survey": [dict(r) for r in self._db.execute("SELECT helpful, most_useful, flag_count, had_eob FROM survey")],
            }

    def delete_case(self, session_hash: str, case_id: str) -> bool:
        case = self.get_case(session_hash, case_id)
        if case is None:
            return False
        self._delete_case_rows([case])
        return True

    # --- expiry -----------------------------------------------------------------------

    def cleanup(self) -> int:
        """Delete expired cases, uploads, and orphaned blobs. Returns blobs removed."""
        now = _iso(self._now())
        with self._lock:
            expired_cases = [r["case_id"] for r in self._db.execute("SELECT case_id FROM cases WHERE expires_at <= ?", (now,))]
            expired_uploads = [
                r["upload_id"] for r in self._db.execute("SELECT upload_id FROM uploads WHERE expires_at <= ?", (now,))
            ]
            with self._db:
                self._db.execute("DELETE FROM cases WHERE expires_at <= ?", (now,))
                self._db.execute("DELETE FROM uploads WHERE expires_at <= ?", (now,))
            live = {r[0] for r in self._db.execute("SELECT case_id FROM cases UNION SELECT upload_id FROM uploads")}
        removed = 0
        for blob_id in expired_cases + expired_uploads:
            self.delete_blob(blob_id)
            removed += 1
        # Orphans (including leftover .tmp files). The age check avoids racing a
        # write in progress, where the blob lands just before its index row.
        cutoff = self._now().timestamp() - ORPHAN_GRACE.total_seconds()
        for path in self.blobs.iterdir():
            if path.stem not in live and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        return removed

    def _delete_case_rows(self, cases: List[CaseRow]) -> None:
        ids = []
        for c in cases:
            ids += [c.case_id, c.bill_upload_id] + c.eob_upload_ids
        with self._lock, self._db:
            for c in cases:
                self._db.execute("DELETE FROM cases WHERE case_id = ?", (c.case_id,))
                for upload_id in [c.bill_upload_id] + c.eob_upload_ids:
                    self._db.execute("DELETE FROM uploads WHERE upload_id = ?", (upload_id,))
        for blob_id in ids:
            self.delete_blob(blob_id)

    def _one(self, sql: str, args: tuple) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchone()

    def close(self) -> None:
        self._db.close()
