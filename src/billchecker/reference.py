"""Optional reference data: NCCI code-pair edits and reference prices.

No data ships with the app. Both sources contain CPT codes, which the AMA
licenses (CMS asks you to accept that license before downloading), so a
deployment must obtain the files itself and point to them:

    BILLCHECKER_NCCI_FILE    CSV: column1,column2,effective_date,deletion_date,modifier_indicator
    BILLCHECKER_PRICES_FILE  CSV: code,reference_price
    BILLCHECKER_PRICES_LABEL text shown with prices, e.g. "Medicare national rate (2026)"

Dates are YYYY-MM-DD; a blank or "*" deletion_date means still in effect.
"""

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import Bill, Eob, Flag, LineItem
from .rules import Rule, _bill_line_evidence, _make_flag, full_code, match_code

# Modifiers that, on the column-2 code, tell the payer the two services were
# distinct (NCCI "PTP-associated modifiers").
BYPASS_MODIFIERS = {
    "59", "XE", "XP", "XS", "XU", "24", "25", "57", "58", "78", "79", "27", "91",
    "LT", "RT", "E1", "E2", "E3", "E4", "FA", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9",
    "TA", "T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "LC", "LD", "RC", "LM", "RI",
}


@dataclass(frozen=True)
class PairEdit:
    effective: date
    deleted: Optional[date]
    modifier_indicator: str  # "0" never allowed together, "1" allowed with a modifier, "9" not applicable

    def active_on(self, day: date) -> bool:
        return self.effective <= day and (self.deleted is None or day < self.deleted)


PairTable = Dict[Tuple[str, str], List[PairEdit]]


def _date(value: str) -> Optional[date]:
    value = (value or "").strip()
    return None if value in ("", "*") else date.fromisoformat(value)


def load_pairs(path: Path) -> PairTable:
    table: PairTable = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            key = (row["column1"].strip().upper(), row["column2"].strip().upper())
            table.setdefault(key, []).append(
                PairEdit(_date(row["effective_date"]), _date(row.get("deletion_date", "")), row["modifier_indicator"].strip())
            )
    return table


def load_prices(path: Path) -> Dict[str, Decimal]:
    prices = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                prices[row["code"].strip().upper()] = Decimal(row["reference_price"].strip())
            except (InvalidOperation, KeyError):
                continue
    return prices


def _modifiers(code: str) -> set:
    base = match_code(code)
    rest = full_code(code)[len(base):] if base else ""
    return {rest[i : i + 2] for i in range(0, len(rest), 2)}


def unbundling_rule(table: PairTable) -> Rule:
    """Two codes billed on the same day that NCCI says are normally billed as one."""

    def unbundled_pair(bill: Bill, eob: Optional[Eob]) -> List[Flag]:
        lines = [li for li in bill.line_items if li.service_date and match_code(li.code, li.code_type) and li.charge > 0]
        flags = []
        for a in lines:
            for b in lines:
                if a is b or a.service_date != b.service_date:
                    continue
                edits = table.get((match_code(a.code), match_code(b.code)), [])
                edit = next((e for e in edits if e.active_on(a.service_date)), None)
                if edit is None or edit.modifier_indicator == "9":
                    continue
                if edit.modifier_indicator == "1" and _modifiers(b.code) & BYPASS_MODIFIERS:
                    continue
                summary = (
                    "Lines {} ({}) and {} ({}) on {} are a pair that Medicare's coding rules (NCCI) normally "
                    "bill as one service. Your plan's rules may differ. This may be worth asking about.".format(
                        a.line_id, a.code, b.line_id, b.code, a.service_date.isoformat()
                    )
                )
                evidence = [_bill_line_evidence(a), _bill_line_evidence(b)]
                flags.append(_make_flag("unbundled_pair", "check", "low", summary, evidence))
        return flags

    return unbundled_pair


def price_context(bill: Bill, prices: Dict[str, Decimal]) -> Dict[str, Dict[str, str]]:
    """Reference price per line, for context only. Never a flag: list prices
    are routinely far above reference rates, so a comparison is not an error."""
    out = {}
    for li in bill.line_items:
        code = match_code(li.code, li.code_type)
        if code is None or code not in prices:
            continue
        units = li.units if li.units and li.units > 0 else Decimal(1)
        out[li.line_id] = {"reference_price": str((prices[code] * units).quantize(Decimal("0.01")))}
    return out


@dataclass(frozen=True)
class Reference:
    pairs: Optional[PairTable] = None
    prices: Optional[Dict[str, Decimal]] = None
    prices_label: str = "Reference price"

    def extra_rules(self) -> List[Rule]:
        return [unbundling_rule(self.pairs)] if self.pairs else []
