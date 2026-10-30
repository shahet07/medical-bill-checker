# Medical Bill Checker

MVP per `medical_bill_checker_design.md` and `medical_bill_checker_hld_lld.md`.

## Status

- [x] Schemas for bill, EOB, and flags (`src/billchecker/models.py`)
- [x] Rules engine, deterministic, no LLM (`src/billchecker/rules.py`)
- [x] Ingest: PDF text layer, scanned PDFs, photos (`src/billchecker/ingest.py`)
- [x] LLM structured extraction with guardrails (`src/billchecker/extraction.py`)
- [x] Swappable LLM providers: Gemini (default) and Claude (`src/billchecker/llm.py`)
- [x] Synthetic test documents and a live extraction eval
- [x] Plain-language explanations with per-item guardrails (`src/billchecker/explanation.py`)
- [x] Letters: itemized-bill request and dispute, template-only (`src/billchecker/letters.py`)
- [x] API: sessions, encrypted 24h storage, background jobs (`src/billchecker/api.py`, `store.py`, `pipeline.py`)
- [x] Web UI: upload, results, letters, delete (`src/billchecker/web/`)
- [x] iPhone photos, multi-page photo uploads, several EOBs per bill
- [x] Feedback per flag and a short survey (`scripts/feedback_report.py`)
- [x] Letters: dispute, itemized request, financial assistance, payment plan, insurer appeal; PDF download
- [x] Checks: duplicates, balance, denial, network, itemization, not on EOB, charge mismatch, payment not applied
- [x] Edit any line or total; glossary; Spanish
- [x] Optional NCCI unbundling and reference prices (engines only; licensed data not included)
- [x] Docker + HTTPS deployment (`deploy/DEPLOY.md`)

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest          # no network, no cost
```

## Running the app

Start the server as below, then open http://127.0.0.1:8765. The page uploads a bill (and an EOB, optionally), shows each line with a plain-language explanation and the flags with their evidence, creates a letter, and lets the user delete everything.

It's plain HTML/CSS/JS with no third-party scripts. A strict Content-Security-Policy blocks inline scripts, and bill data is only inserted as text. `scripts/ui_check.py` drives the whole flow in headless Chrome.

## Running the API

```sh
export BILLCHECKER_KEY=$(.venv/bin/python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())")
export GEMINI_API_KEY=...
export BILLCHECKER_INSECURE_COOKIES=1   # local http only; never in production
.venv/bin/uvicorn --factory billchecker.api:app_from_env --port 8765
```

Keep `BILLCHECKER_KEY` outside the repo. If you lose it, you can no longer read stored data, which is acceptable because everything expires within 24 hours. Data is stored in `~/.billchecker/data`; change it with `BILLCHECKER_DATA_DIR`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/uploads` | Multipart `kind` (`bill`/`eob`) + `file`. Validated immediately (type, size, pages, readable). |
| POST | `/api/cases` | `{bill_upload_id, eob_upload_id?}`. Starts the background job. |
| GET | `/api/cases/{id}` | Status (`queued`, `extracting`, `needs_confirmation`, `ready`, `failed`), data, flags, explanations |
| POST | `/api/cases/{id}/confirm` | `{billed?, patient_balance?}` when totals need confirming |
| POST | `/api/cases/{id}/letter` | `{kind, patient, flag_ids?, note?}`. Patient details are not stored. |
| DELETE | `/api/cases/{id}` | Deletes the case and its uploads immediately |

Security:
- Anonymous session cookie (HttpOnly, Secure, SameSite=Strict). Stored only as a hash.
- Other sessions' IDs return 404.
- Files are encrypted with AES-256-GCM and named by random IDs.
- The SQLite index holds no document content.
- Everything expires after 24 hours, with an hourly cleanup.
- Per-session rate limits.
- Logs contain only IDs and statuses. pdfminer's debug logging is silenced because it prints page text.
- No `/docs` or OpenAPI endpoint.

If the LLM is unreachable or out of quota, the case goes back to `queued` and is retried every 60 seconds, up to 5 attempts.

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
