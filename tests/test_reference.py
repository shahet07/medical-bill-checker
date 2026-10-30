"""Reference-data engines, tested with made-up pairs and prices (no licensed data)."""

from datetime import date
from decimal import Decimal

import pytest

from billchecker.letters import Patient, dispute
from billchecker.reference import Reference, load_pairs, load_prices, price_context, unbundling_rule
from billchecker.rules import run_rules
from factories import line, make_bill

PAIRS_CSV = """column1,column2,effective_date,deletion_date,modifier_indicator
11111,22222,2020-01-01,*,0
33333,44444,2020-01-01,,1
55555,66666,2020-01-01,2025-01-01,0
77777,88888,2020-01-01,*,9
"""


@pytest.fixture
def pairs(tmp_path):
    path = tmp_path / "ncci.csv"
    path.write_text(PAIRS_CSV)
    return load_pairs(path)


def bill_with(*codes):
    return make_bill([line("L{}".format(i), code=c, charge="100.00") for i, c in enumerate(codes, 1)])


def rules_for(pairs, *codes):
    return [f for f in unbundling_rule(pairs)(bill_with(*codes), None)]


def test_load_pairs(pairs):
    assert set(pairs) == {("11111", "22222"), ("33333", "44444"), ("55555", "66666"), ("77777", "88888")}
    [edit] = pairs[("55555", "66666")]
    assert edit.deleted == date(2025, 1, 1) and not edit.active_on(date(2026, 3, 4))


def test_never_together_pair_is_flagged(pairs):
    [flag] = rules_for(pairs, "11111", "22222")
    assert flag.rule == "unbundled_pair" and flag.confidence == "low" and flag.severity == "check"
    assert [e.ref for e in flag.evidence] == ["L1", "L2"]
    assert "NCCI" in flag.summary and "may differ" in flag.summary


def test_order_matters_only_as_listed(pairs):
    # The edit is column1=11111, column2=22222; either line order on the bill matches it once.
    assert len(rules_for(pairs, "22222", "11111")) == 1


def test_modifier_allowed_pair(pairs):
    assert len(rules_for(pairs, "33333", "44444")) == 1  # no modifier
    assert rules_for(pairs, "33333", "44444-59") == []  # distinct-service modifier
    assert rules_for(pairs, "33333", "44444-XU") == []
    assert len(rules_for(pairs, "33333", "44444-26")) == 1  # 26 is not a bypass modifier


def test_deleted_and_not_applicable_edits_are_ignored(pairs):
    assert rules_for(pairs, "55555", "66666") == []
    assert rules_for(pairs, "77777", "88888") == []


def test_different_dates_unrelated_codes_and_rev_codes_ignored(pairs):
    other_day = make_bill([line("L1", code="11111"), line("L2", code="22222", service_date="2026-03-05")])
    assert unbundling_rule(pairs)(other_day, None) == []
    assert rules_for(pairs, "11111", "99213") == []
    rev = make_bill([line("L1", code="11111"), line("L2", code="22222", code_type="REV")])
    assert unbundling_rule(pairs)(rev, None) == []


def test_run_rules_uses_extra_rules_only_when_configured(pairs):
    bill = bill_with("11111", "22222")
    assert run_rules(bill) == []
    assert [f.rule for f in run_rules(bill, extra_rules=Reference(pairs=pairs).extra_rules())] == ["unbundled_pair"]
    assert Reference().extra_rules() == []


def test_unbundled_pair_letter_paragraph(pairs):
    bill = bill_with("11111", "22222")
    [flag] = rules_for(pairs, "11111", "22222")
    text = dispute(bill, None, [flag], Patient("Sam Example", []), date(2026, 4, 15)).text
    assert "National Correct Coding Initiative" in text
    assert text.count("   - Office visit") == 2


# --- Prices -----------------------------------------------------------------------------------


def test_prices_are_context_not_flags(tmp_path):
    path = tmp_path / "prices.csv"
    path.write_text("code,reference_price\n99213,92.50\n85025,bad\n")
    prices = load_prices(path)
    assert prices == {"99213": Decimal("92.50")}
    bill = make_bill([line("L1", code="99213-25", units="2"), line("L2", code="85025"), line("L3", code="0450", code_type="REV")])
    assert price_context(bill, prices) == {"L1": {"reference_price": "185.00"}}
    assert run_rules(bill) == []
