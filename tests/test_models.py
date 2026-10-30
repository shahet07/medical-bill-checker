import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from billchecker.models import Bill, Eob
from factories import bill_data, eob_data, line, make_bill, make_eob


def test_valid_bill_and_eob_parse():
    bill = make_bill()
    eob = make_eob()
    assert bill.line_items[0].charge == Decimal("150.00")
    assert eob.service_lines[0].status == "processed"


def test_json_money_parses_as_exact_decimal():
    raw = json.dumps(bill_data([line("L1", charge="0.10"), line("L2", charge="0.20")]))
    bill = Bill.model_validate_json(raw)
    assert sum(li.charge for li in bill.line_items) == Decimal("0.30")


def test_rejects_unknown_fields():
    data = bill_data()
    data["confidence_notes"] = "invented by the model"
    with pytest.raises(ValidationError):
        Bill.model_validate(data)


def test_rejects_missing_required_field():
    data = bill_data()
    del data["out_of_network_marker"]
    with pytest.raises(ValidationError):
        Bill.model_validate(data)


@pytest.mark.parametrize("bad", ["2026-13-01", "03/04/2026", "yesterday"])
def test_rejects_invalid_dates(bad):
    with pytest.raises(ValidationError):
        make_bill([line("L1", service_date=bad)])


def test_rejects_more_than_two_decimal_places():
    with pytest.raises(ValidationError):
        make_bill([line("L1", charge="150.005")])


def test_rejects_duplicate_line_ids():
    with pytest.raises(ValidationError):
        make_bill([line("L1"), line("L1")])
    with pytest.raises(ValidationError):
        Eob.model_validate(eob_data([{**eob_data()["service_lines"][0]}] * 2))


def test_rejects_bad_line_id_format():
    with pytest.raises(ValidationError):
        make_bill([line("line-1")])


def test_rejects_reversed_date_range():
    with pytest.raises(ValidationError):
        make_bill(dates_of_service={"start": "2026-03-05", "end": "2026-03-04"})


def test_rejects_invalid_eob_status():
    with pytest.raises(ValidationError):
        make_eob([dict(eob_data()["service_lines"][0], status="rejected")])


def test_models_are_immutable():
    bill = make_bill()
    with pytest.raises(ValidationError):
        bill.itemized = False
