# Deploying for testers

One small Linux server (1 vCPU, 2 GB RAM is plenty for validation) running three containers:
- PostgreSQL
- the app
- Caddy, which gets and renews the HTTPS certificate automatically

## Before you start
1. **A paid LLM tier.** Real bills must not go through Gemini's free tier. Use a paid Gemini key or Claude, and check the provider's data-retention terms.
2. **A domain** (or subdomain), with its DNS A record pointing at the server's IP.
3. **Legal review.** The service now stores accounts and saved bills for 90 days, and an opt-in research dataset. Have the privacy policy and terms reviewed before real users sign up.

## Steps
```sh
git clone <your repo> && cd medical-bill-checker
cp deploy/.env.example deploy/.env      # fill in DOMAIN, POSTGRES_PASSWORD, BILLCHECKER_KEY, provider keys
docker compose -f deploy/docker-compose.yml up -d --build
```
Open `https://<your domain>`. The certificate appears within a minute of first start.

## What is stored, and for how long
| Data | Where | Kept |
|---|---|---|
| Accounts (email, Argon2 password hash, consent choice) | `users` | Until the user deletes their account |
| Login sessions (hashed tokens) | `sessions` | 14 days |
| Uploaded files (encrypted) | `uploads.data` | 24 hours |
| Extracted data, flags, explanations (encrypted) | `cases.result` | 90 days, or until the user deletes it |
| Feedback and survey answers (no content) | `flag_feedback`, `survey` | Kept for analysis |
| Research dataset (only with consent; codes, amounts, flags; no names, providers, dates, IDs) | `research_cases` | Kept; deleted if the user deletes the case or account, or withdraws consent while the case exists |
| Usage events (counts; pseudonymous user key) | `events` | Kept; unlinked when an account is deleted |

## Operating notes
- **Run exactly one app container.** Background jobs and rate limits live in that process.
- **Admin tasks** (stats, password reset, delete a user, export research data):
  ```sh
  docker compose -f deploy/docker-compose.yml exec app python -m billchecker.admin stats
  docker compose -f deploy/docker-compose.yml exec app python -m billchecker.admin reset-password someone@example.com
  docker compose -f deploy/docker-compose.yml exec app python -m billchecker.admin export-research /tmp/research.jsonl
  ```
  There is no password-reset email yet; use `reset-password` and give the temporary password to the tester privately.
- **Backups:** saved bills now matter, so back up the database daily, for example:
  `docker compose -f deploy/docker-compose.yml exec db pg_dump -U billchecker billchecker | gzip > backup-$(date +%F).sql.gz`
  Keep backups **7 days at most** and store them encrypted, so deleted data does not live on in old backups. Back up `BILLCHECKER_KEY` separately: without it, saved results in a backup cannot be read.
- **Logs** contain IDs and statuses only. Caddy access logs are turned off.
- **Updating:** `git pull && docker compose -f deploy/docker-compose.yml up -d --build`. Database changes apply automatically on start.
- **Keys:** keep `deploy/.env` out of git (it's in `.gitignore`).
- **Database password:** PostgreSQL sets `POSTGRES_PASSWORD` only when its data volume is first created. Changing it later in `deploy/.env` does not change the existing database's password; change it inside Postgres (`ALTER USER billchecker PASSWORD '...'`) as well, or the app can't connect.

## Hosts that fit
Any VPS that runs Docker works, for example DigitalOcean, Hetzner, Linode or AWS Lightsail, at roughly $6–12/month. You can also use a managed PostgreSQL from your host instead of the `db` container: remove the `db` service and set `DATABASE_URL` in `deploy/.env`.
