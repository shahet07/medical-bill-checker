"""Billing error radar: billing problems that many patients report at the same provider.

Patients who opt in (separately from the research dataset) contribute one
report per flag on their bill: the provider's name, the type of check, and
for line-level checks the procedure code. No amounts, dates, descriptions,
or anything about the patient. A pattern is shown only once at least K
different people have reported it (k-anonymity; default 10), and counts are
shown as ranges, never exact numbers. Reports a patient marks "No, it was
fine" don't count; "Yes, a real problem" counts as confirmed.

Reports are deleted when the patient deletes the case or account or
withdraws consent. Limitation: someone creating many fake accounts could
inflate a pattern, so patterns are signals to look into, not findings.
"""

import re
from typing import Any, Dict, List, Optional, Sequence

from .models import Bill, Flag, LineItem
from .rules import match_code

DEFAULT_K = 10
# Line-level checks also record which procedure code was involved.
LINE_RULES = {"duplicate_line", "billed_after_denial", "not_on_eob", "charge_mismatch", "unbundled_pair"}
_SUFFIXES = {"inc", "llc", "pc", "pllc", "ltd", "corp", "corporation", "co", "lp", "llp", "pa"}


def normalize_provider(name: Optional[str]) -> Optional[str]:
    """'Riverside Medical Group, Inc.' and 'RIVERSIDE MEDICAL GROUP' -> 'riverside medical group'."""
    if not name:
        return None
    words = re.sub(r"[^a-z0-9 ]+", " ", name.lower().replace("&", " and ")).split()
    if words and words[0] == "the":
        words = words[1:]
    while words and words[-1] in _SUFFIXES:
        words = words[:-1]
    key = " ".join(words)
    return key if len(key) >= 3 else None


def radar_items(bill: Bill, flags: Sequence[Flag]) -> List[Dict[str, Any]]:
    lines: Dict[str, LineItem] = {li.line_id: li for li in bill.line_items}
    items = []
    for f in flags:
        code = None
        if f.rule in LINE_RULES:
            refs = [e.ref for e in f.evidence if e.source == "bill" and e.ref in lines]
            if refs:
                li = lines[refs[0]]
                code = match_code(li.code, li.code_type)
        items.append({"flag_id": f.flag_id, "rule": f.rule, "code": code})
    return items


def bucket(n: int) -> str:
    for low, high in ((10, 24), (25, 49), (50, 99)):
        if n <= high:
            return "{}–{}".format(max(low, 0), high)
    return "100+"


def present(patterns: List[Dict[str, Any]], k: int) -> List[Dict[str, Any]]:
    out = []
    for p in patterns:
        users = p["users"]
        if users < k:
            continue
        share = p["confirmed_users"] / users
        out.append(
            {
                "rule": p["rule"],
                "code": p["code"] or None,
                "reports": bucket(users) if k >= 10 else "{}+".format(k),
                "confirmed": "most" if share >= 0.5 else "some" if share > 0 else None,
                "last_month": p["last_month"],
            }
        )
    return out
