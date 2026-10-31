from datetime import date
from decimal import Decimal

import pytest

from billchecker.letters import Patient
from billchecker.models import Bill, Eob
from billchecker.refunds import Payment, Statement, find_refunds, group_episodes, refund_letter
from synthetic import CASES, expected_bill, expected_eob

BY_NAME = {c.name: c for c in CASES}
SAM = Patient("Sam Example", ["12 Elm Street"])


def statement(case_name, case_id, statement_date=None, with_eob=True, **bill_over):
    case = BY_NAME[case_name]
    data = expected_bill(case.bill)
    if statement_date:
        data["statement_date"] = statement_date
    data.update(bill_over)
    eob = Eob.model_validate(expected_eob(case.eob)) if with_eob and case.eob else None
    return Statement(case_id, "2026-04-0{}T00:00:00+00:00".format(len(case_id)), Bill.model_validate(data), eob)


def pay(case_id, amount, day, note="", pid=None):
    return Payment(pid or "p{}{}".format(amount, day), case_id, Decimal(amount), date(2026, 3, day), note)


# --- Grouping ------------------------------------------------------------------------------


def test_statements_for_the_same_visit_group_together():
    a = statement("clean", "a", "2026-03-10", with_eob=False)
    b = statement("credit", "b", "2026-04-20")
    other_day = statement("clean", "c", dates_of_service={"start": "2026-05-01", "end": "2026-05-01"},
                          line_items=[dict(li, service_date="2026-05-01") for li in expected_bill(BY_NAME["clean"].bill)["line_items"]])
    other_provider = statement("clean", "d", provider_name="Lakeside Clinic")
    groups = group_episodes([a, b, other_day, other_provider])
    assert sorted(sorted(s.case_id for s in g) for g in groups) == [["a", "b"], ["c"], ["d"]]


# --- Findings ------------------------------------------------------------------------------


def test_paid_at_visit_then_insurance_paid_is_overpaid():
    # Paid the full $205.00 at the visit; the EOB says the patient's share is $40.00.
    [ep] = find_refunds([statement("clean", "a")], [pay("a", "205.00", 4, "paid at check-in")])
    assert ep.owed == Decimal("40.00") and ep.paid == Decimal("205.00")
    assert [(f.kind, f.amount) for f in ep.findings] == [("overpaid", Decimal("165.00"))]
    assert ep.estimate == Decimal("165.00")


def test_credit_balance_on_latest_statement():
    first = statement("clean", "a", "2026-03-10", with_eob=False)
    later = statement("credit", "bb", "2026-04-20")
    [ep] = find_refunds([first, later], [])
    assert [(f.kind, f.amount) for f in ep.findings] == [("credit_balance", Decimal("45.00"))]
    assert ep.latest.case_id == "bb"


def test_credit_and_overpayment_are_not_double_counted():
    [ep] = find_refunds([statement("credit", "a")], [pay("a", "85.00", 4)])
    kinds = {f.kind: f.amount for f in ep.findings}
    assert kinds == {"credit_balance": Decimal("45.00"), "overpaid": Decimal("45.00")}
    assert ep.estimate == Decimal("45.00")


def test_duplicate_payment_within_a_week():
    [ep] = find_refunds([statement("clean", "a")], [pay("a", "40.00", 4, pid="x"), pay("a", "40.00", 9, pid="y")])
    assert ("duplicate_payment", Decimal("40.00")) in [(f.kind, f.amount) for f in ep.findings]
    [ep2] = find_refunds([statement("clean", "a")], [pay("a", "40.00", 4, pid="x"), pay("a", "40.00", 25, pid="y")])
    assert all(f.kind != "duplicate_payment" for f in ep2.findings)


def test_paid_exactly_what_was_owed_is_not_a_refund():
    [ep] = find_refunds([statement("clean", "a")], [pay("a", "40.00", 4)])
    assert ep.findings == [] and ep.estimate == Decimal("0")


def test_newest_eob_per_claim_wins():
    old = statement("clean", "a", "2026-03-10")
    new = statement("clean", "bb", "2026-04-20")
    new.eob = Eob.model_validate(dict(expected_eob(BY_NAME["clean"].eob), totals={"patient_responsibility": "15.00", "source": None}))
    [ep] = find_refunds([old, new], [pay("a", "40.00", 4)])
    assert ep.owed == Decimal("15.00")
    assert [(f.kind, f.amount) for f in ep.findings] == [("overpaid", Decimal("25.00"))]


def test_unknown_owed_means_no_overpayment_claim():
    [ep] = find_refunds([statement("clean", "a", with_eob=False)], [pay("a", "500.00", 4)])
    assert ep.owed is None and ep.findings == []


# --- Letter --------------------------------------------------------------------------------


def test_refund_letter_states_only_known_amounts():
    import re

    [ep] = find_refunds([statement("credit", "a")], [pay("a", "85.00", 4, "paid at check-in")])
    text = refund_letter(ep, SAM, date(2026, 5, 1)).text
    assert "Re: Request for refund of overpayment" in text
    assert "- $85.00 on March 4, 2026 (paid at check-in)" in text
    assert "responsibility for these services as $40.00, and I have paid $85.00." in text
    assert "That means I paid $45.00 more than I owe." in text
    assert "shows a credit balance of $45.00" in text
    allowed = {"85.00", "40.00", "45.00"}
    assert set(re.findall(r"\$([\d,]+\.\d{2})", text)) <= allowed


def test_no_refund_letter_without_a_finding():
    [ep] = find_refunds([statement("clean", "a")], [])
    with pytest.raises(ValueError):
        refund_letter(ep, SAM, date(2026, 5, 1))
