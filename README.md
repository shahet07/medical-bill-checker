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
- [x] Feedback per flag and a short survey (`scripts/admin.py stats`)
- [x] Letters: dispute, itemized request, financial assistance, payment plan, insurer appeal; PDF download
- [x] Checks: duplicates, balance, denial, network, itemization, not on EOB, charge mismatch, payment not applied
- [x] Edit any line or total; glossary; Spanish
- [x] Optional NCCI unbundling and reference prices (engines only; licensed data not included)
- [x] Accounts (email + password), saved bills for 90 days, opt-in research dataset, usage analytics, PostgreSQL
- [x] Docker + HTTPS deployment (`deploy/DEPLOY.md`)

## Setup

```sh
python3 -m venv .venv               # Python 3.10 or newer
.venv/bin/pip install -e ".[dev]"
scripts/dev_db.sh start             # private PostgreSQL in .pgdata, port 54329
.venv/bin/python -m pytest          # no network, no LLM cost
```

## Running the app

```sh
scripts/dev_db.sh start
cp .env.dev.example .env.dev        # first time only; then generate a key into it (see the file)
set -a; . ./.env.dev; set +a
export GEMINI_API_KEY=...
.venv/bin/uvicorn --factory billchecker.api:app_from_env --port 8765
```

Open http://127.0.0.1:8765 and create an account. Users can upload a bill (and EOBs), see each line explained and the flags with their evidence, create letters, revisit past bills from **My bills**, and manage or delete their account.

The page is plain HTML/CSS/JS with no third-party scripts. A strict Content-Security-Policy blocks inline scripts, and bill data is only inserted as text. `scripts/ui_check.py` drives the whole flow in headless Chrome.

## Use it from an AI assistant (MCP)

`billchecker-mcp` is a local [Model Context Protocol](https://modelcontextprotocol.io) server. It lets Claude Desktop, Claude Code, or another MCP client check bills on your computer. It stores nothing: no database and no accounts.

| Tool | What it does |
|---|---|
| `check_bill` | Reads bill and EOB files (PDF or photos) with the configured LLM, runs every check, and explains each line and flag |
| `check_extracted_bill` | Runs the checks on bill/EOB data the assistant extracted itself. No LLM, no network, no API key. |
| `create_letter` | Writes any of the five letters, optionally as a PDF. Flags are recomputed from the data, so the assistant can't add flags the checks didn't raise. |

Resources `billchecker://schema/bill` and `billchecker://schema/eob` describe the data format. The `review_bill` prompt runs the whole workflow.

**Claude Code:**
```sh
claude mcp add billchecker --env GEMINI_API_KEY=... -- /path/to/medical-bill-checker/.venv/bin/billchecker-mcp
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "billchecker": {
      "command": "/path/to/medical-bill-checker/.venv/bin/billchecker-mcp",
      "env": { "GEMINI_API_KEY": "..." }
    }
  }
}
```

Leave out the API key to use only `check_extracted_bill` and `create_letter`. The assistant then reads the bill itself, and the checks still run here. Requires Python 3.10+ and `pip install -e ".[mcp]"`.

## Accounts and data

- **Login:** email and password. Passwords are hashed with Argon2id. Login attempts are limited per IP address, and an account locks for 15 minutes after 10 failed tries. Error messages don't reveal whether an email has an account. Changing your password logs out your other sessions.
- **Retention:** uploaded files are deleted after 24 hours. Results are kept for 90 days, or until the user deletes the bill or their account.
- **Research dataset:** opt-in at signup, and changeable under My account. It holds codes, amounts, flags and the case month, with no names, providers, account numbers, dates or files. See `src/billchecker/research.py`.
- **Usage analytics:** event counts with a pseudonymous user key, which is unlinked when an account is deleted.
- **Admin:** `scripts/admin.py stats | reset-password EMAIL | delete-user EMAIL --yes | export-research FILE`.

Full table of what is stored and for how long: `deploy/DEPLOY.md`.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/register` | `{email, password, research_consent}`. Logs in. |
| POST | `/api/auth/login` · `/api/auth/logout` | Log in / out |
| GET | `/api/auth/session` · `/api/auth/me` | Who is logged in |
| POST | `/api/auth/password` | `{current_password, new_password}` |
| PUT | `/api/auth/consent` | `{research_consent}` |
| DELETE | `/api/auth/account` | `{password}`. Deletes the account and all its data. |
| POST | `/api/uploads` | Multipart `kind` (`bill`/`eob`) + one or more `file`. Validated immediately. |
| GET | `/api/cases` | The user's bills, newest first |
| POST | `/api/cases` | `{bill_upload_id, eob_upload_ids?, language?}`. Starts the background job. |
| GET | `/api/cases/{id}` | Status, data, flags, explanations |
| POST | `/api/cases/{id}/confirm` · PUT `/bill` · PUT `/language` | Confirm totals, correct lines, switch explanation language |
| POST | `/api/cases/{id}/letter` | `{kind, patient, flag_ids?, note?, format?}`. Patient details are not stored. |
| POST | `/api/cases/{id}/feedback` · `/survey` | Validation feedback |
| DELETE | `/api/cases/{id}` | Deletes the bill and its uploads immediately |

Security:
- The login cookie is HttpOnly, Secure and SameSite=Strict, with the token stored only as a hash. State-changing requests from other sites are refused.
- Another user's IDs return 404.
- Files and results are encrypted with AES-256-GCM inside PostgreSQL. Each value is bound to its row.
- Rate limits apply per user, plus per IP address for login and signup.
- Logs contain only IDs and statuses. pdfminer's debug logging is silenced because it prints page text.
- There is no `/docs` or OpenAPI endpoint.

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

Python 3.10 or newer (developed on 3.13; the Docker image uses 3.12). `anthropic` stays below 1.x until its client-API changes are migrated.

## License

MIT. See [LICENSE](LICENSE).
