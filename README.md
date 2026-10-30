# Medical Bill Checker

MVP per `medical_bill_checker_design.md` and `medical_bill_checker_hld_lld.md`.

## Status

- [x] Schemas for bill, EOB, and flags (`src/billchecker/models.py`)
- [x] Rules engine, deterministic, no LLM (`src/billchecker/rules.py`)
- [x] Ingest: PDF text layer, scanned PDFs, photos (`src/billchecker/ingest.py`)
- [x] LLM structured extraction with guardrails (`src/billchecker/extraction.py`)
- [x] Swappable LLM providers: Gemini (default) and Claude (`src/billchecker/llm.py`)
- [x] Synthetic test documents and a live extraction eval
- [ ] Explanation module
- [x] Letters: itemized-bill request and dispute, template-only (`src/billchecker/letters.py`)
- [ ] API and UI

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest          # no network, no cost
```

## Test documents

`tests/synthetic.py` defines six fictional cases: clean, duplicate, balance mismatch, denial, network mismatch, and summary-only. There are also photo, scan, and screenshot versions of some of them. Each case is defined once, as data, and from that we render the document and build its expected extraction.

```sh
.venv/bin/python scripts/make_fixtures.py     # writes them to fixtures/ to look at
```

## LLM provider

| Setting | Values | Default |
|---|---|---|
| `BILLCHECKER_PROVIDER` | `gemini`, `claude` | `gemini` |
| `BILLCHECKER_MODEL` | any model ID for that provider | `gemini-3.6-flash` / `claude-opus-5` |
| API key | `GEMINI_API_KEY` (from aistudio.google.com) / `ANTHROPIC_API_KEY` | none |

> **Privacy: the Gemini free tier is for synthetic data only.** Google's pricing page says free-tier content is "used to improve our products", and human reviewers may read it. The design requires that user data never be used for training. So **real bills, including those from validation testers, must go to a paid tier** (Gemini paid or Claude), with retention terms checked first.

## Live extraction eval

This sends every synthetic document to the configured provider. It reports field mismatches, whether the expected flags were raised, tokens, and estimated cost.

```sh
export GEMINI_API_KEY=...
.venv/bin/python scripts/eval_extraction.py --yes
BILLCHECKER_PROVIDER=claude ANTHROPIC_API_KEY=... .venv/bin/python scripts/eval_extraction.py --yes
```

The free tier has low per-minute limits. The Gemini client retries 429s with backoff, so a full run may take a few minutes.

## How extraction works

1. **Ingest** sniffs the file type from its bytes, not its name. PDF pages with a text layer go to the model as text. Scanned pages and photos go as images, downscaled to 1568px. Photos are re-encoded, which removes EXIF data such as location. Rejected: over 20 MB, over 20 pages, HEIC (for now), anything else unreadable.
2. **The model transcribes** the pages into a JSON schema, using the provider's structured-output mode. The system prompt marks document text as untrusted data. Money is sent as strings so amounts stay exact.
3. **Code validates** the output against the Pydantic models. On failure it retries once with the errors appended. The document is the same prefix both times, so the provider's prompt cache can make the retry cheap. A second failure, a refusal, or a truncated response sets `needs_confirmation`, and the raw output is kept.
4. **Guardrails:**
   - Every `source_page` must exist.
   - On text pages, each line's `source_text` must be found on the page. If it isn't, a warning is added and confidence is set to low.
   - Total charges must match the sum of line items, or `needs_confirmation` is set and the total is cleared.
   - The account number is masked to its last 4 characters in code, whatever the model returns.
5. Outages and rate limits that persist after retries raise `LLMUnavailable`, so the job can stay queued. Safety blocks, including Gemini's `SPII` (sensitive personal info) block, count as refusals and go to user confirmation.

## Changes from the LLD

- `Bill.out_of_network_marker`: the text on the bill that says "out of network". `network_mismatch` needs it.
- `BillTotals.source` / `EobTotals.source`: where the totals appear, so balance flags can show real evidence.
- `EobLine.line_id` (`E1`, `E2`, ...): lets evidence point at a specific EOB line.
- `flag_id` is deterministic (`rule:source.ref,...`) instead of a UUID, so results are the same on every rerun.
- Matching drops modifiers (`99213-25` → `99213`). Revenue codes never match.
- `duplicate_line` confidence is **medium**, not high: identical repeated lines can be legitimate. Lines with different modifiers (e.g. LT/RT) are not counted as duplicates.
- `balance_mismatch` drops to medium confidence when the bill has service dates the EOB does not cover.
- `billed_after_denial` fires only when the bill's patient balance is above zero. If an EOB line match has mixed statuses, the line is skipped.
- Severity: `review` means money may be at stake and the provider is worth contacting. `check` means read and verify before acting.
- PDF handling uses pdfplumber + pypdfium2, not PyMuPDF. PyMuPDF is AGPL-licensed, which would be a problem for a closed-source product.

## Python version

The system Python here is 3.9, which reached end of life in October 2025. Two dependencies are pinned because of it: `anthropic<1` and `reportlab<4.3`. Moving to 3.11+ lifts both pins.
