"""Refund finder: money the provider may owe the patient, followed across statements.

Patients often pay at the visit or pay a first statement, and the insurer pays
later; the extra sits on the account as a credit balance unless someone asks
for it back. This module groups a patient's saved bills into visits (same
provider, overlapping service dates), combines the EOBs and the payments the
patient entered, and finds:

- credit_balance: the latest statement for the visit shows a negative amount due;
- overpaid: the patient paid more than the EOBs say they owe for the visit;
- duplicate_payment: the same amount paid twice within a week.

Everything is computed from saved data on request; nothing new is stored
except the payments the patient enters (encrypted, 90 days).
"""

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .letters import Letter, Patient, _letter, long_date, usd
from .models import Bill, Eob
from .radar import normalize_provider

TOLERANCE = Decimal("0.01")
DUPLICATE_WINDOW = timedelta(days=7)


@dataclass
class Statement:
    case_id: str
    created_at: str
    bill: Bill
    eob: Optional[Eob]

    @property
    def dates(self) -> set:
        ds = {li.service_date for li in self.bill.line_items if li.service_date}
        dos = self.bill.dates_of_service
        if dos.start and dos.end and (dos.end - dos.start).days <= 366:
            ds |= {dos.start + timedelta(days=n) for n in range((dos.end - dos.start).days + 1)}
        elif dos.start or dos.end:
            ds.add(dos.start or dos.end)
        return ds

    @property
    def order_key(self) -> Tuple:
        return (self.bill.statement_date or date.min, self.created_at)


@dataclass(frozen=True)
class Payment:
    payment_id: str
    case_id: str
    amount: Decimal
    paid_on: date
    note: str


@dataclass
class Finding:
    kind: str  # credit_balance | overpaid | duplicate_payment
    amount: Decimal


@dataclass
class Episode:
    episode_id: str
    provider_name: Optional[str]
    service_dates: List[date]
    statements: List[Statement]
    payments: List[Payment] = field(default_factory=list)
    owed: Optional[Decimal] = None  # patient responsibility per the EOBs, all claims
    paid: Decimal = Decimal("0")
    latest_balance: Optional[Decimal] = None
    findings: List[Finding] = field(default_factory=list)

    @property
    def estimate(self) -> Decimal:
        """Likely refund. Credit balance and overpayment usually describe the same money, so take the larger."""
        main = max([f.amount for f in self.findings if f.kind in ("credit_balance", "overpaid")] or [Decimal("0")])
        return main if main > 0 else max([f.amount for f in self.findings] or [Decimal("0")])

    @property
    def latest(self) -> Statement:
        return self.statements[-1]


def _owed(statements: Sequence[Statement]) -> Optional[Decimal]:
    """Patient responsibility summed over distinct claims, using the newest EOB for each claim."""
    by_claim: Dict[str, Decimal] = {}
    for st in statements:  # oldest first, so newer EOBs replace older ones
        if st.eob is None:
            continue
        if st.eob.totals.patient_responsibility is None:
            return None
        by_claim[st.eob.claim_id or "case:" + st.case_id] = st.eob.totals.patient_responsibility
    return sum(by_claim.values(), Decimal("0")) if by_claim else None


def group_episodes(statements: Sequence[Statement]) -> List[List[Statement]]:
    """Same provider and at least one shared service date -> same visit (transitively)."""
    groups: List[Tuple[Optional[str], set, List[Statement]]] = []
    for st in statements:
        key = normalize_provider(st.bill.provider_name)
        dates = st.dates
        matches = [g for g in groups if key is not None and g[0] == key and (g[1] & dates)]
        if not matches:
            groups.append((key, set(dates), [st]))
            continue
        merged_dates, merged = set(dates), [st]
        for g in matches:
            merged_dates |= g[1]
            merged += g[2]
            groups.remove(g)
        groups.append((key, merged_dates, merged))
    return [g[2] for g in groups]


def find_refunds(statements: Sequence[Statement], payments: Sequence[Payment]) -> List[Episode]:
    episodes = []
    for group in group_episodes(statements):
        group = sorted(group, key=lambda s: s.order_key)
        dates = sorted(set().union(*(s.dates for s in group)))
        provider = group[-1].bill.provider_name
        seed = "{}|{}".format(normalize_provider(provider) or group[0].case_id, dates[0].isoformat() if dates else group[0].case_id)
        ep = Episode(hashlib.sha256(seed.encode()).hexdigest()[:16], provider, dates, group)
        case_ids = {s.case_id for s in group}
        ep.payments = sorted([p for p in payments if p.case_id in case_ids], key=lambda p: p.paid_on)
        ep.paid = sum((p.amount for p in ep.payments), Decimal("0"))
        ep.owed = _owed(group)
        ep.latest_balance = ep.latest.bill.totals.patient_balance

        if ep.latest_balance is not None and ep.latest_balance < -TOLERANCE:
            ep.findings.append(Finding("credit_balance", abs(ep.latest_balance)))
        if ep.owed is not None and ep.payments and ep.paid > ep.owed + TOLERANCE:
            ep.findings.append(Finding("overpaid", ep.paid - ep.owed))
        for i, a in enumerate(ep.payments):
            for b in ep.payments[i + 1 :]:
                if a.amount == b.amount and abs(b.paid_on - a.paid_on) <= DUPLICATE_WINDOW:
                    ep.findings.append(Finding("duplicate_payment", a.amount))
                    break
        episodes.append(ep)
    return sorted(episodes, key=lambda e: (-e.estimate, e.latest.order_key), reverse=False)


def refund_letter(ep: Episode, patient: Patient, today: date, note: Optional[str] = None) -> Letter:
    """Ask the provider to refund a credit or overpayment. Every amount comes from the data or the
    payments the patient entered."""
    if not ep.findings:
        raise ValueError("no refund signal for this visit")
    when = ""
    if ep.service_dates:
        first, last = ep.service_dates[0], ep.service_dates[-1]
        when = " on " + long_date(first) if first == last else " from {} to {}".format(long_date(first), long_date(last))
    body = ["I am writing about payments on the account above for services{}.".format(when)]
    if ep.payments:
        body.append(
            "My records show these payments:\n"
            + "\n".join(
                "- {} on {}{}".format(usd(p.amount), long_date(p.paid_on), " ({})".format(p.note) if p.note else "")
                for p in ep.payments
            )
        )
    kinds = {f.kind: f.amount for f in ep.findings}
    facts = []
    if ep.owed is not None and ep.payments:
        facts.append(
            "My insurer's Explanation of Benefits shows my total responsibility for these services as {}, "
            "and I have paid {}.".format(usd(ep.owed), usd(ep.paid))
        )
    if "overpaid" in kinds:
        facts.append("That means I paid {} more than I owe.".format(usd(kinds["overpaid"])))
    if "credit_balance" in kinds:
        dated = " dated " + long_date(ep.latest.bill.statement_date) if ep.latest.bill.statement_date else ""
        facts.append("Your statement{} shows a credit balance of {} on my account.".format(dated, usd(kinds["credit_balance"])))
    if "duplicate_payment" in kinds:
        facts.append("It appears a payment of {} may have been made twice.".format(usd(kinds["duplicate_payment"])))
    body.append(" ".join(facts))
    body.append(
        "Please refund the overpayment to me, or explain in writing why it is being held. Please also send me an "
        "itemized statement showing all payments and adjustments applied to this account."
    )
    return _letter("refund_request", "Request for refund of overpayment", ep.latest.bill, ep.latest.eob, patient, today, body, note)


def episode_out(ep: Episode) -> Dict[str, Any]:
    return {
        "episode_id": ep.episode_id,
        "provider_name": ep.provider_name,
        "service_dates": [d.isoformat() for d in ep.service_dates],
        "statements": [
            {
                "case_id": s.case_id,
                "statement_date": s.bill.statement_date.isoformat() if s.bill.statement_date else None,
                "amount_due": str(s.bill.totals.patient_balance) if s.bill.totals.patient_balance is not None else None,
                "has_eob": s.eob is not None,
            }
            for s in ep.statements
        ],
        "payments": [
            {"payment_id": p.payment_id, "amount": str(p.amount), "paid_on": p.paid_on.isoformat(), "note": p.note}
            for p in ep.payments
        ],
        "owed": str(ep.owed) if ep.owed is not None else None,
        "paid": str(ep.paid),
        "latest_balance": str(ep.latest_balance) if ep.latest_balance is not None else None,
        "findings": [{"kind": f.kind, "amount": str(f.amount)} for f in ep.findings],
        "estimate": str(ep.estimate),
    }
