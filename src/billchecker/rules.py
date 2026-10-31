"""Deterministic rules engine.

Each rule is a pure function (bill, eob | None) -> list[Flag]: no I/O, no LLM.
Rules are conservative: when data is missing or ambiguous they stay silent,
because a false accusation costs more trust than a missed flag.
"""

import re
from collections import defaultdict
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Tuple

from .models import Bill, Eob, EobLine, Evidence, Flag, LineItem

Rule = Callable[[Bill, Optional[Eob]], List[Flag]]

DENIED_STATUSES = ("denied", "not_processed")
BALANCE_TOLERANCE = Decimal("0.01")

# A 5-character CPT/HCPCS code, optionally followed by 2-character modifiers.
_MATCH_CODE_RE = re.compile(r"^([A-Z0-9]{5})(?:[-\s:]*[A-Z0-9]{2})*$")


def _money(value: Decimal) -> str:
    return "${:,.2f}".format(value)


def match_code(code: Optional[str], code_type: Optional[str] = None) -> Optional[str]:
    """Base CPT/HCPCS code used to match bill lines to EOB lines.

    Modifiers are dropped ("99213-25" -> "99213"). Revenue codes and anything
    that does not look like a CPT/HCPCS code return None, meaning "unmatchable".
    """
    if code is None or code_type == "REV":
        return None
    m = _MATCH_CODE_RE.match(code.strip().upper())
    return m.group(1) if m else None


def full_code(code: str) -> str:
    """Code including modifiers, with formatting differences removed."""
    return re.sub(r"[-\s:]", "", code.strip().upper())


def _bill_line_evidence(line: LineItem) -> Evidence:
    return Evidence(source="bill", ref=line.line_id, page=line.source_page, text=line.source_text)


def _eob_line_evidence(line: EobLine) -> Evidence:
    return Evidence(source="eob", ref=line.line_id, page=line.source_page, text=line.source_text)


def _flag_id(rule: str, evidence: List[Evidence]) -> str:
    return "{}:{}".format(rule, ",".join("{}.{}".format(e.source, e.ref) for e in evidence))


def _make_flag(rule: str, severity: str, confidence: str, summary: str, evidence: List[Evidence]) -> Flag:
    return Flag(
        flag_id=_flag_id(rule, evidence),
        rule=rule,
        severity=severity,
        confidence=confidence,
        summary=summary,
        evidence=evidence,
    )


# --- Rules ------------------------------------------------------------------


def duplicate_line(bill: Bill, eob: Optional[Eob]) -> List[Flag]:
    """Same date, code (with modifiers), units, and charge on more than one line.

    Lines missing a date or code are skipped. Modifiers are kept in the key
    because e.g. LT/RT on the same code is a legitimate pair, not a duplicate.
    Confidence is medium: identical repeated lines can be legitimate.
    """
    if not bill.itemized:
        return []
    groups: Dict[Tuple, List[LineItem]] = defaultdict(list)
    for line in bill.line_items:
        if line.service_date is None or not line.code or line.charge <= 0:
            continue
        groups[(line.service_date, full_code(line.code), line.units, line.charge)].append(line)

    flags = []
    for (service_date, _, _, charge), lines in groups.items():
        if len(lines) < 2:
            continue
        ids = ", ".join(li.line_id for li in lines)
        summary = (
            "Lines {} have the same code ({}), service date ({}), and charge ({}). "
            "This may be a duplicate charge and needs checking.".format(
                ids, lines[0].code, service_date.isoformat(), _money(charge)
            )
        )
        flags.append(
            _make_flag("duplicate_line", "review", "medium", summary, [_bill_line_evidence(li) for li in lines])
        )
    return flags


def balance_mismatch(bill: Bill, eob: Optional[Eob]) -> List[Flag]:
    """Bill's patient balance differs from the EOB's patient responsibility.

    Confidence drops to medium when the bill has service dates the EOB does
    not cover, since the balance may then include other claims.
    """
    if eob is None:
        return []
    billed = bill.totals.patient_balance
    owed = eob.totals.patient_responsibility
    if billed is None or owed is None or abs(billed - owed) <= BALANCE_TOLERANCE:
        return []

    bill_dates = {li.service_date for li in bill.line_items if li.service_date}
    eob_dates = {sl.service_date for sl in eob.service_lines if sl.service_date}
    covers_bill = bool(eob_dates) and bill_dates <= eob_dates
    confidence = "high" if covers_bill else "medium"

    evidence = [
        Evidence(
            source="bill",
            ref="totals",
            page=bill.totals.source.page if bill.totals.source else None,
            text=bill.totals.source.text if bill.totals.source else "Patient balance: {}".format(_money(billed)),
        ),
        Evidence(
            source="eob",
            ref="totals",
            page=eob.totals.source.page if eob.totals.source else None,
            text=eob.totals.source.text if eob.totals.source else "Patient responsibility: {}".format(_money(owed)),
        ),
    ]
    summary = (
        "The bill asks you to pay {}, but your insurer's EOB says your responsibility is {} "
        "(a difference of {}). This needs checking.".format(_money(billed), _money(owed), _money(abs(billed - owed)))
    )
    if not covers_bill:
        summary += " The bill may also include services not on this EOB."
    return [_make_flag("balance_mismatch", "check", confidence, summary, evidence)]


def billed_after_denial(bill: Bill, eob: Optional[Eob]) -> List[Flag]:
    """A bill line matches EOB lines that were all denied or not processed,
    and the bill asks the patient to pay something.

    Matching is exact on (service_date, base code). Lines that cannot be
    matched (no date, no code, revenue code) are skipped, not guessed.
    """
    if eob is None or not (bill.totals.patient_balance and bill.totals.patient_balance > 0):
        return []

    eob_index: Dict[Tuple, List[EobLine]] = defaultdict(list)
    for sl in eob.service_lines:
        code = match_code(sl.code)
        if sl.service_date and code:
            eob_index[(sl.service_date, code)].append(sl)

    flags = []
    for line in bill.line_items:
        code = match_code(line.code, line.code_type)
        if line.service_date is None or code is None or line.charge <= 0:
            continue
        matches = eob_index.get((line.service_date, code), [])
        # Mixed statuses (e.g. one denied, one processed) are ambiguous; skip.
        if not matches or any(m.status not in DENIED_STATUSES for m in matches):
            continue
        reasons = sorted({m.denial_reason for m in matches if m.denial_reason})
        summary = (
            "Line {} ({}, {}) is on your bill, but your EOB shows the insurer {} this service.".format(
                line.line_id,
                line.code,
                line.service_date.isoformat(),
                "denied" if all(m.status == "denied" for m in matches) else "did not process",
            )
        )
        if reasons:
            summary += " Reason given: {}.".format("; ".join(reasons))
        summary += " Check whether you should be billed for it."
        evidence = [_bill_line_evidence(line)] + [_eob_line_evidence(m) for m in matches]
        flags.append(_make_flag("billed_after_denial", "review", "medium", summary, evidence))
    return flags


def network_mismatch(bill: Bill, eob: Optional[Eob]) -> List[Flag]:
    """The bill explicitly says out of network, but every EOB line with a
    known network status says in network."""
    if eob is None or bill.out_of_network_marker is None:
        return []
    known = [sl for sl in eob.service_lines if sl.network_status != "unknown"]
    if not known or any(sl.network_status != "in_network" for sl in known):
        return []

    marker = bill.out_of_network_marker
    evidence = [Evidence(source="bill", ref="network_marker", page=marker.page, text=marker.text)]
    evidence += [_eob_line_evidence(sl) for sl in known]
    summary = (
        "Your bill describes this care as out of network, but your EOB processed it as in network. "
        "Out-of-network billing can cost you more, so this needs checking."
    )
    return [_make_flag("network_mismatch", "check", "medium", summary, evidence)]


def no_itemization(bill: Bill, eob: Optional[Eob]) -> List[Flag]:
    """Bill is a summary total without line items."""
    if bill.itemized and bill.line_items:
        return []
    if bill.itemized and bill.totals.billed is None:
        # Nothing on the bill at all; that is an extraction problem, not a flag.
        return []

    src = bill.totals.source
    if src:
        evidence = [Evidence(source="bill", ref="totals", page=src.page, text=src.text)]
    elif bill.totals.billed is not None:
        evidence = [Evidence(source="bill", ref="totals", page=None, text="Total: {}".format(_money(bill.totals.billed)))]
    else:
        evidence = [Evidence(source="bill", ref="totals", page=None, text="No line items or total found on the bill.")]
    summary = (
        "This bill shows a total but does not list the individual services. "
        "You can ask the provider for an itemized bill to see what you are being charged for."
    )
    return [_make_flag("no_itemization", "check", "high", summary, evidence)]


def _eob_index(eob: Eob) -> Dict[Tuple, List[EobLine]]:
    index: Dict[Tuple, List[EobLine]] = defaultdict(list)
    for sl in eob.service_lines:
        code = match_code(sl.code)
        if sl.service_date and code:
            index[(sl.service_date, code)].append(sl)
    return index


def _matchable(line: LineItem) -> Optional[Tuple]:
    code = match_code(line.code, line.code_type)
    if line.service_date is None or code is None or line.charge <= 0:
        return None
    return (line.service_date, code)


def not_on_eob(bill: Bill, eob: Optional[Eob]) -> List[Flag]:
    """A bill line the EOB does not list, on a date the EOB does cover.

    Requiring the EOB to have other services on that date avoids flagging
    lines that simply belong to a different claim.
    """
    if eob is None:
        return []
    index = _eob_index(eob)
    eob_dates = {sl.service_date for sl in eob.service_lines if sl.service_date}
    flags = []
    for line in bill.line_items:
        key = _matchable(line)
        if key is None or key in index or key[0] not in eob_dates:
            continue
        summary = (
            "Line {} ({}, {}, {}) is on your bill, but your insurance EOB does not list it for that date. "
            "It may not have been sent to your insurance. This needs checking.".format(
                line.line_id, line.code, line.service_date.isoformat(), _money(line.charge)
            )
        )
        flags.append(_make_flag("not_on_eob", "check", "medium", summary, [_bill_line_evidence(line)]))
    return flags


def charge_mismatch(bill: Bill, eob: Optional[Eob]) -> List[Flag]:
    """The bill's charge for a service differs from what the EOB says was billed to the insurer."""
    if eob is None:
        return []
    index = _eob_index(eob)
    flags = []
    for line in bill.line_items:
        key = _matchable(line)
        matches = index.get(key, []) if key else []
        # Only a single unambiguous match with a known billed amount.
        if len(matches) != 1 or matches[0].billed is None:
            continue
        claimed = matches[0].billed
        if abs(claimed - line.charge) <= BALANCE_TOLERANCE:
            continue
        summary = (
            "Line {} ({}, {}) shows a charge of {}, but your EOB says the provider billed your insurer {} "
            "for this service. This needs checking.".format(
                line.line_id, line.code, line.service_date.isoformat(), _money(line.charge), _money(claimed)
            )
        )
        evidence = [_bill_line_evidence(line), _eob_line_evidence(matches[0])]
        flags.append(_make_flag("charge_mismatch", "check", "medium", summary, evidence))
    return flags


def payment_not_applied(bill: Bill, eob: Optional[Eob]) -> List[Flag]:
    """The EOB shows the insurer paid more than the bill shows in payments and adjustments."""
    if eob is None or bill.totals.adjustments is None:
        return []
    paid = [sl.insurer_paid for sl in eob.service_lines]
    if not paid or any(p is None for p in paid):
        return []
    insurer_paid = sum(paid, Decimal("0"))
    shown = abs(bill.totals.adjustments)
    if insurer_paid <= 0 or shown >= insurer_paid - BALANCE_TOLERANCE:
        return []
    # Only when the EOB covers every service date on the bill (same visit).
    bill_dates = {li.service_date for li in bill.line_items if li.service_date}
    eob_dates = {sl.service_date for sl in eob.service_lines if sl.service_date}
    if not bill_dates or not bill_dates <= eob_dates:
        return []
    src = bill.totals.source
    evidence = [
        Evidence(
            source="bill",
            ref="totals",
            page=src.page if src else None,
            text="Payments and adjustments: {}".format(_money(bill.totals.adjustments)),
        )
    ] + [_eob_line_evidence(sl) for sl in eob.service_lines if sl.insurer_paid]
    summary = (
        "Your EOB shows your insurer paid {}, but this bill shows only {} in payments and adjustments. "
        "The insurance payment may not have been applied yet. This needs checking.".format(
            _money(insurer_paid), _money(shown)
        )
    )
    return [_make_flag("payment_not_applied", "review", "medium", summary, evidence)]


def credit_balance(bill: Bill, eob: Optional[Eob]) -> List[Flag]:
    """The statement shows a negative amount due: the provider is holding a credit for the patient."""
    balance = bill.totals.patient_balance
    if balance is None or balance >= -BALANCE_TOLERANCE:
        return []
    src = bill.totals.source
    evidence = [
        Evidence(
            source="bill",
            ref="totals",
            page=src.page if src else None,
            text=src.text if src else "Amount due: {}".format(_money(balance)),
        )
    ]
    summary = (
        "Your statement shows a credit balance of {}. That usually means you paid more than you owe "
        "and the provider may owe you a refund. This needs checking.".format(_money(abs(balance)))
    )
    return [_make_flag("credit_balance", "review", "high", summary, evidence)]


RULES: List[Rule] = [
    duplicate_line,
    balance_mismatch,
    billed_after_denial,
    network_mismatch,
    no_itemization,
    not_on_eob,
    charge_mismatch,
    payment_not_applied,
    credit_balance,
]


# Rules that compare the bill against the EOBs as a whole. If some EOBs could
# not be read, these would compare against an incomplete picture, so they are skipped.
NEEDS_ALL_EOBS = {balance_mismatch, not_on_eob, payment_not_applied}


def run_rules(
    bill: Bill, eob: Optional[Eob] = None, eob_complete: bool = True, extra_rules: Optional[List[Rule]] = None
) -> List[Flag]:
    """extra_rules: rules that need optional reference data (see reference.py)."""
    flags: List[Flag] = []
    for rule in RULES + list(extra_rules or []):
        if not eob_complete and rule in NEEDS_ALL_EOBS:
            continue
        flags.extend(rule(bill, eob))
    return flags
