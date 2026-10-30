# Deploying for testers

One small Linux server (1 vCPU, 1–2 GB RAM is plenty for validation) running two containers:
- the app
- Caddy, which gets and renews the HTTPS certificate automatically

## Before you start
1. **A paid LLM tier.** Real bills must not go through Gemini's free tier. Use a paid Gemini key or Claude, and check the provider's data-retention terms.
2. **A domain** (or subdomain), with its DNS A record pointing at the server's IP.
3. **Legal review** of the privacy and CPT questions in the design doc.

## Steps
```sh
git clone <your repo> && cd medical-bill-checker
cp deploy/.env.example deploy/.env      # fill in DOMAIN, BILLCHECKER_KEY, provider keys
docker compose -f deploy/docker-compose.yml up -d --build
```
Open `https://<your domain>`. The certificate appears within a minute of first start.

## Operating notes
- **Run exactly one app container.** Background jobs and rate limits live in that process.
- **Data** lives in the `data` volume, encrypted, and expires after 24 hours. Validation feedback (no document content) stays there too. To read it, copy the index out and run the report on your machine:
  ```sh
  mkdir -p feedback && docker compose -f deploy/docker-compose.yml cp app:/data/index.sqlite3 feedback/
  .venv/bin/python scripts/feedback_report.py feedback
  ```
- **Backups:** don't back up the `data` volume. Uploads are meant to disappear.
- **Logs** contain IDs and statuses only. Caddy access logs are turned off.
- **Updating:** `git pull && docker compose -f deploy/docker-compose.yml up -d --build`. Cases in progress are lost on restart, which is acceptable for testing.
- **Keys:** keep `deploy/.env` out of git (it's in `.gitignore`). Rotating `BILLCHECKER_KEY` makes current cases unreadable; they would have expired within 24 hours anyway.

## Hosts that fit
Any VPS that runs Docker works, for example DigitalOcean, Hetzner, Linode or AWS Lightsail, at roughly $5–12/month. A platform host such as Fly.io or Render also works if it provides a persistent volume, but there you'd use the platform's HTTPS instead of Caddy.
