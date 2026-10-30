"""Every synthetic file through ingest -> extraction -> rules.

The LLM is replaced by the case's expected extraction, so this checks that
the fixtures, guardrails, and rules agree with each other. Live model
accuracy is measured separately by scripts/eval_extraction.py.
"""

import pytest

from billchecker.extraction import extract_bill, extract_eob
from billchecker.ingest import ingest
from billchecker.rules import run_rules
from conftest import FakeLLM
from synthetic import CASES


def _extract(f):
    doc = ingest(f.path.read_bytes())
    fn = extract_bill if f.kind == "bill" else extract_eob
    return fn(doc, FakeLLM(f.expected))


def test_every_fixture_extracts_cleanly(fixture_files):
    for f in fixture_files:
        result = _extract(f)
        assert (f.path.name, result.status, result.warnings) == (f.path.name, "ok", [])


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_case_raises_expected_flags(case, fixture_files):
    files = {(f.kind, f.variant): f for f in fixture_files if f.case is case}
    eob = _extract(files[("eob", "pdf")]).data if case.eob else None
    for (kind, variant), f in files.items():
        if kind != "bill":
            continue
        flags = run_rules(_extract(f).data, eob)
        assert sorted(fl.rule for fl in flags) == sorted(case.expected_rules), variant
