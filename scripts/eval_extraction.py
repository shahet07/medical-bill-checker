"""Run real LLM extraction over the synthetic fixtures and score it.

This calls the provider's API. Gemini's free tier costs nothing but has low
rate limits; Claude costs a few cents per document. It will not run without --yes.

    .venv/bin/python scripts/eval_extraction.py --yes                      # Gemini (default)
    BILLCHECKER_PROVIDER=claude .venv/bin/python scripts/eval_extraction.py --yes
    BILLCHECKER_MODEL=gemini-3.8-flash .venv/bin/python scripts/eval_extraction.py --yes
    .venv/bin/python scripts/eval_extraction.py --yes --only photo

For each file it reports: extraction status, field mismatches against the
expected values, whether the rules engine raised the expected flags, tokens,
and estimated cost.
"""

import argparse
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from billchecker.extraction import extract_bill, extract_eob  # noqa: E402
from billchecker.ingest import ingest  # noqa: E402
from billchecker.llm import USAGE_FIELDS, LLMResponse, make_llm  # noqa: E402
from billchecker.models import Bill, Eob  # noqa: E402
from billchecker.rules import run_rules  # noqa: E402
from synthetic import FixtureFile, build_files  # noqa: E402

# USD per million tokens (input, output). Check current pricing before relying on these.
# Gemini entries are the free tier; paid-tier prices differ.
PRICES = {
    "gemini-3.8-flash": (0.0, 0.0),
    "gemini-3.6-flash": (0.0, 0.0),
    "gemini-3.5-flash-lite": (0.0, 0.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
CACHE_READ, CACHE_WRITE = 0.1, 1.25

BILL_LINE_FIELDS = ("service_date", "code", "units", "charge")
EOB_LINE_FIELDS = ("service_date", "code", "billed", "allowed", "insurer_paid", "patient_responsibility", "status", "network_status")


class RecordingLLM:
    def __init__(self, inner):
        self.inner = inner
        self.usage = {k: 0 for k in USAGE_FIELDS}
        self.calls = 0

    def generate(self, system, content, schema) -> LLMResponse:
        resp = self.inner.generate(system, content, schema)
        self.calls += 1
        for k, v in (resp.usage or {}).items():
            self.usage[k] += v
        return resp


def cost(model: str, usage: Dict[str, int]) -> Optional[float]:
    if model not in PRICES:
        return None
    inp, out = PRICES[model]
    return (
        usage["input_tokens"] * inp
        + usage["cache_read_input_tokens"] * inp * CACHE_READ
        + usage["cache_creation_input_tokens"] * inp * CACHE_WRITE
        + usage["output_tokens"] * out
    ) / 1_000_000


def _norm(v: Any) -> Any:
    if isinstance(v, Decimal) or (isinstance(v, (int, float)) and not isinstance(v, bool)):
        return Decimal(str(v)).normalize()
    if isinstance(v, str):
        try:
            return Decimal(v).normalize()
        except Exception:
            return v.strip().upper()
    return v


def diff(expected: Dict, actual) -> List[str]:
    """Field-level differences that matter for the rules. Wording fields are ignored."""
    got = actual.model_dump(mode="json")
    out = []
    is_bill = isinstance(actual, Bill)
    key, fields = ("line_items", BILL_LINE_FIELDS) if is_bill else ("service_lines", EOB_LINE_FIELDS)
    exp_lines, got_lines = expected[key], got[key]
    if len(exp_lines) != len(got_lines):
        out.append("{}: expected {} rows, got {}".format(key, len(exp_lines), len(got_lines)))
    for i, (e, g) in enumerate(zip(exp_lines, got_lines)):
        for f in fields:
            if _norm(e[f]) != _norm(g[f]):
                out.append("{}[{}].{}: expected {!r}, got {!r}".format(key, i, f, e[f], g[f]))
    totals = ("billed", "adjustments", "patient_balance") if is_bill else ("patient_responsibility",)
    for f in totals:
        if _norm(expected["totals"][f]) != _norm(got["totals"][f]):
            out.append("totals.{}: expected {!r}, got {!r}".format(f, expected["totals"][f], got["totals"][f]))
    if is_bill:
        if expected["itemized"] != got["itemized"]:
            out.append("itemized: expected {}, got {}".format(expected["itemized"], got["itemized"]))
        if (expected["out_of_network_marker"] is None) != (got["out_of_network_marker"] is None):
            out.append("out_of_network_marker: expected {}".format("present" if expected["out_of_network_marker"] else "absent"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="confirm you want to make paid API calls")
    ap.add_argument("--only", help="only files whose name contains this text")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        files = build_files(Path(tmp))
        if args.only:
            files = [f for f in files if args.only in f.path.name]
        if not args.yes:
            print("This will make {} or more API calls. Re-run with --yes to proceed.".format(len(files)))
            return 2

        llm = RecordingLLM(make_llm())
        model = llm.inner.model
        print("model: {}  files: {}\n".format(model, len(files)))
        results: Dict[str, Any] = {}
        failures = 0
        for f in files:
            before = dict(llm.usage)
            start = time.time()
            fn = extract_bill if f.kind == "bill" else extract_eob
            result = fn(ingest(f.path.read_bytes()), llm)
            spent = {k: llm.usage[k] - before[k] for k in USAGE_FIELDS}
            problems = list(result.problems) + list(result.warnings)
            if result.data is not None:
                problems += diff(f.expected, result.data)
            results[f.path.name] = (f, result)
            failures += bool(problems) or result.status != "ok"
            c = cost(model, spent)
            print(
                "{:<30} {:<18} {:>3} issue(s)  in={:<6} out={:<6} {}  {:.1f}s".format(
                    f.path.name,
                    result.status,
                    len(problems),
                    spent["input_tokens"] + spent["cache_read_input_tokens"] + spent["cache_creation_input_tokens"],
                    spent["output_tokens"],
                    "${:.4f}".format(c) if c is not None else "",
                    time.time() - start,
                )
            )
            for p in problems:
                print("    - " + p)

        print("\nFlags (rules engine on the extracted data):")
        for f, result in [v for v in results.values() if v[0].kind == "bill"]:
            eob_entry = next((r for g, r in results.values() if g.case is f.case and g.kind == "eob" and g.variant == "pdf"), None)
            eob = eob_entry.data if eob_entry else None
            if f.case.eob and eob is None:
                print("  {:<30} skipped (EOB not extracted)".format(f.path.name))
                continue
            if result.data is None:
                print("  {:<30} skipped (bill not extracted)".format(f.path.name))
                failures += 1
                continue
            got = sorted(fl.rule for fl in run_rules(result.data, eob))
            ok = got == sorted(f.case.expected_rules)
            failures += not ok
            print("  {:<30} {}  expected={} got={}".format(f.path.name, "OK  " if ok else "MISS", sorted(f.case.expected_rules), got))

        total = cost(model, llm.usage)
        print("\ncalls: {}  total cost: {}".format(llm.calls, "${:.4f}".format(total) if total is not None else "unknown for this model"))
        return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
