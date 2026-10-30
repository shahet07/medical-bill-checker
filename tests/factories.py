"""Builders for test bills and EOBs. Defaults describe a clean, itemized bill."""

from typing import Any, Dict, List, Optional

from billchecker.models import Bill, Eob

DOS = "2026-03-04"


def line(line_id: str, code: Optional[str] = "99213", charge: str = "150.00", **kw: Any) -> Dict[str, Any]:
    data = {
        "line_id": line_id,
        "service_date": DOS,
        "description": "Office visit",
        "code": code,
        "code_type": "CPT",
        "units": "1",
        "charge": charge,
        "source_page": 1,
        "source_text": "{} {} {}".format(DOS, code, charge),
    }
    data.update(kw)
    return data


def eob_line(line_id: str, code: Optional[str] = "99213", status: str = "processed", **kw: Any) -> Dict[str, Any]:
    data = {
        "line_id": line_id,
        "service_date": DOS,
        "code": code,
        "billed": "150.00",
        "allowed": "100.00",
        "insurer_paid": "80.00",
        "patient_responsibility": "20.00",
        "status": status,
        "denial_reason": None,
        "network_status": "in_network",
        "source_page": 1,
        "source_text": "{} {} {}".format(DOS, code, status),
    }
    data.update(kw)
    return data


def bill_data(lines: Optional[List[Dict[str, Any]]] = None, **kw: Any) -> Dict[str, Any]:
    data = {
        "schema_version": "1.0",
        "provider_name": "Example Clinic",
        "account_number_redacted": "****1234",
        "statement_date": "2026-04-01",
        "dates_of_service": {"start": DOS, "end": DOS},
        "line_items": [line("L1")] if lines is None else lines,
        "totals": {
            "billed": "150.00",
            "adjustments": "-130.00",
            "patient_balance": "20.00",
            "source": {"page": 1, "text": "Amount due: $20.00"},
        },
        "itemized": True,
        "out_of_network_marker": None,
        "extraction_confidence": "high",
    }
    data.update(kw)
    return data


def eob_data(lines: Optional[List[Dict[str, Any]]] = None, **kw: Any) -> Dict[str, Any]:
    data = {
        "schema_version": "1.0",
        "insurer": "Example Health",
        "claim_id": "C-1",
        "service_lines": [eob_line("E1")] if lines is None else lines,
        "totals": {
            "patient_responsibility": "20.00",
            "source": {"page": 1, "text": "You may owe the provider: $20.00"},
        },
    }
    data.update(kw)
    return data


def make_bill(lines: Optional[List[Dict[str, Any]]] = None, **kw: Any) -> Bill:
    return Bill.model_validate(bill_data(lines, **kw))


def make_eob(lines: Optional[List[Dict[str, Any]]] = None, **kw: Any) -> Eob:
    return Eob.model_validate(eob_data(lines, **kw))


def totals(patient_balance: Optional[str], billed: Optional[str] = "150.00", source: Any = None) -> Dict[str, Any]:
    return {"billed": billed, "adjustments": None, "patient_balance": patient_balance, "source": source}
