"""The anonymized research record kept for a case, with the user's consent.

What it contains is listed here in one place on purpose. It holds no names,
provider, insurer, account or member numbers, claim IDs, service dates
(only the month the case was created, stored separately), descriptions,
document text, or files.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional

from .models import Bill, Eob, Flag
from .rules import match_code


def _s(value: Optional[Decimal]) -> Optional[str]:
    return str(value) if value is not None else None


def research_record(
    bill: Bill,
    eob: Optional[Eob],
    flags: List[Flag],
    *,
    eob_count: int,
    eob_status: str,
    language: str,
    user_edited: bool,
    model: Optional[str],
    prompt_versions: Dict[str, str],
) -> Dict[str, Any]:
    paid = [sl.insurer_paid for sl in eob.service_lines] if eob else []
    return {
        "language": language,
        "itemized": bill.itemized,
        "extraction_confidence": bill.extraction_confidence,
        "user_edited": user_edited,
        "eob_count": eob_count,
        "eob_status": eob_status,
        "lines": [
            {
                "code": match_code(li.code, li.code_type) or (li.code_type and li.code_type.lower()) or None,
                "code_type": li.code_type,
                "units": _s(li.units),
                "charge": _s(li.charge),
            }
            for li in bill.line_items
        ],
        "totals": {
            "billed": _s(bill.totals.billed),
            "adjustments": _s(bill.totals.adjustments),
            "patient_balance": _s(bill.totals.patient_balance),
        },
        "eob": {
            "patient_responsibility": _s(eob.totals.patient_responsibility),
            "insurer_paid": _s(sum(paid, Decimal("0"))) if paid and all(p is not None for p in paid) else None,
            "line_statuses": sorted(sl.status for sl in eob.service_lines),
            "network": sorted({sl.network_status for sl in eob.service_lines}),
        }
        if eob
        else None,
        "flags": [{"rule": f.rule, "confidence": f.confidence} for f in flags],
        "model": model,
        "prompt_versions": prompt_versions,
    }
