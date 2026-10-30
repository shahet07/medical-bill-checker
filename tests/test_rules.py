from billchecker.rules import (
    RULES,
    balance_mismatch,
    billed_after_denial,
    duplicate_line,
    match_code,
    network_mismatch,
    no_itemization,
    run_rules,
)
from factories import eob_line, line, make_bill, make_eob, totals


def refs(flag):
    return [(e.source, e.ref) for e in flag.evidence]


# --- match_code ---------------------------------------------------------------


def test_match_code_strips_modifiers_and_case():
    assert match_code("99213-25") == "99213"
    assert match_code(" 99213 25 ") == "99213"
    assert match_code("j1100") == "J1100"
    assert match_code("27447-LT-59") == "27447"


def test_match_code_refuses_revenue_and_unknown_codes():
    assert match_code("0450", "REV") is None
    assert match_code("99213", "REV") is None
    assert match_code("0450") is None
    assert match_code("ABC") is None
    assert match_code(None) is None


# --- duplicate_line -------------------------------------------------------------


def test_duplicate_flags_identical_lines_with_both_rows_as_evidence():
    bill = make_bill([line("L1"), line("L2", code="85025", charge="40.00"), line("L3")])
    [flag] = duplicate_line(bill, None)
    assert flag.rule == "duplicate_line"
    assert flag.severity == "review"
    assert flag.confidence == "medium"
    assert refs(flag) == [("bill", "L1"), ("bill", "L3")]
    assert "$150.00" in flag.summary


def test_duplicate_ignores_formatting_differences_in_code():
    bill = make_bill([line("L1", code="99213-25"), line("L2", code="99213 25")])
    assert len(duplicate_line(bill, None)) == 1


def test_duplicate_not_flagged_when_modifiers_differ():
    bill = make_bill([line("L1", code="27447-LT"), line("L2", code="27447-RT")])
    assert duplicate_line(bill, None) == []


def test_duplicate_not_flagged_when_date_charge_or_units_differ():
    assert duplicate_line(make_bill([line("L1"), line("L2", service_date="2026-03-05")]), None) == []
    assert duplicate_line(make_bill([line("L1"), line("L2", charge="151.00")]), None) == []
    assert duplicate_line(make_bill([line("L1"), line("L2", units="2")]), None) == []


def test_duplicate_skips_lines_missing_code_or_date():
    assert duplicate_line(make_bill([line("L1", code=None), line("L2", code=None)]), None) == []
    assert duplicate_line(make_bill([line("L1", service_date=None), line("L2", service_date=None)]), None) == []


def test_duplicate_skips_credits_and_zero_lines():
    bill = make_bill([line("L1", charge="-50.00"), line("L2", charge="-50.00")])
    assert duplicate_line(bill, None) == []


def test_duplicate_requires_itemized_bill():
    bill = make_bill([line("L1"), line("L2")], itemized=False)
    assert duplicate_line(bill, None) == []


# --- balance_mismatch -------------------------------------------------------------


def test_balance_mismatch_flags_with_both_amounts():
    bill = make_bill(totals=totals("95.00", source={"page": 2, "text": "Please pay $95.00"}))
    [flag] = balance_mismatch(bill, make_eob())
    assert flag.severity == "check"
    assert flag.confidence == "high"
    assert "$95.00" in flag.summary and "$20.00" in flag.summary and "$75.00" in flag.summary
    assert refs(flag) == [("bill", "totals"), ("eob", "totals")]
    assert flag.evidence[0].page == 2


def test_balance_within_one_cent_is_not_flagged():
    assert balance_mismatch(make_bill(totals=totals("20.01")), make_eob()) == []
    assert balance_mismatch(make_bill(totals=totals("20.00")), make_eob()) == []


def test_balance_mismatch_needs_eob_and_both_amounts():
    assert balance_mismatch(make_bill(totals=totals("95.00")), None) == []
    assert balance_mismatch(make_bill(totals=totals(None)), make_eob()) == []
    eob = make_eob(totals={"patient_responsibility": None, "source": None})
    assert balance_mismatch(make_bill(totals=totals("95.00")), eob) == []


def test_balance_mismatch_medium_confidence_when_bill_has_dates_not_on_eob():
    bill = make_bill([line("L1"), line("L2", service_date="2026-02-10")], totals=totals("95.00"))
    [flag] = balance_mismatch(bill, make_eob())
    assert flag.confidence == "medium"
    assert "services not on this EOB" in flag.summary


def test_balance_mismatch_falls_back_to_amount_text_without_source():
    [flag] = balance_mismatch(make_bill(totals=totals("95.00")), make_eob())
    assert flag.evidence[0].page is None
    assert flag.evidence[0].text == "Patient balance: $95.00"


# --- billed_after_denial ---------------------------------------------------------


def denied(line_id="E1", **kw):
    return eob_line(line_id, status="denied", patient_responsibility="0.00", **kw)


def test_billed_after_denial_flags_matching_denied_line():
    eob = make_eob([denied(denial_reason="Not medically necessary")])
    [flag] = billed_after_denial(make_bill(), eob)
    assert flag.severity == "review"
    assert flag.confidence == "medium"
    assert refs(flag) == [("bill", "L1"), ("eob", "E1")]
    assert "denied" in flag.summary
    assert "Not medically necessary" in flag.summary


def test_billed_after_denial_matches_across_modifiers():
    bill = make_bill([line("L1", code="99213-25")])
    assert len(billed_after_denial(bill, make_eob([denied(code="99213")]))) == 1


def test_billed_after_denial_flags_not_processed():
    [flag] = billed_after_denial(make_bill(), make_eob([eob_line("E1", status="not_processed")]))
    assert "did not process" in flag.summary


def test_billed_after_denial_ignores_processed_lines():
    assert billed_after_denial(make_bill(), make_eob()) == []


def test_billed_after_denial_skips_mixed_status_matches():
    eob = make_eob([denied("E1"), eob_line("E2", status="processed")])
    assert billed_after_denial(make_bill(), eob) == []


def test_billed_after_denial_does_not_guess_without_exact_match():
    eob = make_eob([denied()])
    assert billed_after_denial(make_bill([line("L1", code=None)]), eob) == []
    assert billed_after_denial(make_bill([line("L1", service_date="2026-03-05")]), eob) == []
    assert billed_after_denial(make_bill([line("L1", code="0450", code_type="REV")]), eob) == []
    assert billed_after_denial(make_bill(), make_eob([denied(code=None)])) == []


def test_billed_after_denial_silent_when_patient_owes_nothing():
    eob = make_eob([denied()])
    assert billed_after_denial(make_bill(totals=totals("0.00")), eob) == []
    assert billed_after_denial(make_bill(totals=totals(None)), eob) == []


def test_billed_after_denial_needs_eob():
    assert billed_after_denial(make_bill(), None) == []


# --- network_mismatch -------------------------------------------------------------

OON = {"page": 1, "text": "Out-of-network provider"}


def test_network_mismatch_flags_when_eob_all_in_network():
    [flag] = network_mismatch(make_bill(out_of_network_marker=OON), make_eob())
    assert flag.severity == "check"
    assert refs(flag) == [("bill", "network_marker"), ("eob", "E1")]
    assert flag.evidence[0].text == "Out-of-network provider"


def test_network_mismatch_needs_explicit_marker():
    assert network_mismatch(make_bill(), make_eob()) == []


def test_network_mismatch_silent_when_eob_mixed_or_unknown():
    mixed = make_eob([eob_line("E1"), eob_line("E2", network_status="out_of_network")])
    unknown = make_eob([eob_line("E1", network_status="unknown")])
    assert network_mismatch(make_bill(out_of_network_marker=OON), mixed) == []
    assert network_mismatch(make_bill(out_of_network_marker=OON), unknown) == []


def test_network_mismatch_ignores_unknown_lines_alongside_in_network():
    eob = make_eob([eob_line("E1"), eob_line("E2", network_status="unknown")])
    [flag] = network_mismatch(make_bill(out_of_network_marker=OON), eob)
    assert refs(flag) == [("bill", "network_marker"), ("eob", "E1")]


def test_network_mismatch_needs_eob():
    assert network_mismatch(make_bill(out_of_network_marker=OON), None) == []


# --- no_itemization ---------------------------------------------------------------


def test_no_itemization_flags_summary_bill():
    bill = make_bill([], itemized=False, totals=totals("500.00", billed="500.00", source={"page": 1, "text": "Total charges $500.00"}))
    [flag] = no_itemization(bill, None)
    assert flag.confidence == "high"
    assert flag.evidence[0].text == "Total charges $500.00"


def test_no_itemization_flags_empty_lines_with_total():
    [flag] = no_itemization(make_bill([], totals=totals("500.00", billed="500.00")), None)
    assert flag.evidence[0].text == "Total: $500.00"


def test_no_itemization_silent_for_itemized_bill():
    assert no_itemization(make_bill(), None) == []


def test_no_itemization_silent_when_nothing_extracted():
    assert no_itemization(make_bill([], totals=totals(None, billed=None)), None) == []


# --- engine -----------------------------------------------------------------------


def test_clean_bill_produces_no_flags():
    assert run_rules(make_bill(), make_eob()) == []
    assert run_rules(make_bill()) == []


def test_flag_ids_are_deterministic():
    bill = make_bill([line("L1"), line("L2")], totals=totals("95.00"))
    first = [f.flag_id for f in run_rules(bill, make_eob())]
    assert first == [f.flag_id for f in run_rules(bill, make_eob())]
    assert first == ["duplicate_line:bill.L1,bill.L2", "balance_mismatch:bill.totals,eob.totals"]


def test_rules_never_raise_on_sparse_data():
    sparse_bill = make_bill(
        [line("L1", code=None, service_date=None, units=None, code_type=None)],
        totals=totals(None, billed=None),
        dates_of_service={"start": None, "end": None},
    )
    sparse_eob = make_eob(
        [eob_line("E1", code=None, service_date=None, status="unknown", network_status="unknown")],
        totals={"patient_responsibility": None, "source": None},
    )
    for rule in RULES:
        assert rule(sparse_bill, sparse_eob) == []
        assert rule(sparse_bill, None) == []
