"""Tamper-evident dispute packets.

When a dispute letter is created, the app signs a small packet describing what
the letter relies on: the evidence quoted from the bill/EOB (with page
numbers), a SHA-256 fingerprint of every uploaded document, and a fingerprint
of the letter text itself. The letter carries a link (and QR code) to a public
verification page.

Anyone holding the link can check that:
- the packet was issued by this service and has not been altered since
  (Ed25519 signature over a canonical JSON encoding);
- a document they hold is byte-for-byte the one the patient uploaded (the
  page hashes the file in their browser; the file is never uploaded);
- the letter they received matches the one issued (letter fingerprint).

The packet holds only what the letter already states, plus fingerprints. It
never includes the patient's name, contact details, account number, or the
documents themselves. Packets disappear with their case (90 days, or sooner
if the patient deletes it).
"""

import base64
import hashlib
import json
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .models import Bill, Eob, Flag

PACKET_VERSION = 1


def new_packet_id() -> str:
    return secrets.token_urlsafe(12)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def signing_key(master_key: bytes) -> Ed25519PrivateKey:
    """Derive the packet signing key from the app's master key (HKDF), so no new secret is needed."""
    seed = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"billchecker packet signing v1").derive(master_key)
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_key_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def canonical(payload: Dict[str, Any]) -> bytes:
    """Deterministic bytes to sign: sorted keys, no whitespace, UTF-8."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(payload: Dict[str, Any], key: Ed25519PrivateKey) -> str:
    return base64.b64encode(key.sign(canonical(payload))).decode()


def verify(payload: Dict[str, Any], signature_b64: str, public_b64: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_b64)).verify(base64.b64decode(signature_b64), canonical(payload))
        return True
    except (InvalidSignature, ValueError):
        return False


def build_payload(
    packet_id: str,
    issued_at: datetime,
    bill: Bill,
    eob: Optional[Eob],
    flags: Sequence[Flag],
    letter_text: str,
    documents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """documents: [{"kind": "bill"|"eob", "sha256": [one per uploaded file]}]."""
    return {
        "v": PACKET_VERSION,
        "packet_id": packet_id,
        "issued_at": issued_at.replace(microsecond=0).isoformat(),
        "provider": bill.provider_name,
        "insurer": eob.insurer if eob else None,
        "statement_date": bill.statement_date.isoformat() if bill.statement_date else None,
        "letter_sha256": sha256_hex(letter_text.encode()),
        "documents": documents,
        "items": [
            {
                "rule": f.rule,
                "evidence": [
                    {"source": e.source, "page": e.page, "text": e.text, "text_sha256": sha256_hex(e.text.encode())}
                    for e in f.evidence
                ],
            }
            for f in flags
        ],
    }
