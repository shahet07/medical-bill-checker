# Real uploads on the GitHub Pages website

The website on GitHub Pages can't check bills by itself. With a Clyvexa server
online, the app on the website sends uploads to that server. This sets one up
for free: the server on **Render**, the database on **Neon**.

Free-tier notes: the server sleeps after about 15 minutes without visitors, so
the first visit after that waits up to a minute while it wakes (the app says
so). Neon's free database is small but plenty for this.

## 1. Database (Neon)

1. Sign up at https://neon.tech and create a project (any name, region near you).
2. Copy the **connection string**. It looks like
   `postgresql://user:password@ep-....neon.tech/neondb?sslmode=require`.

## 2. Server (Render)

1. Sign up at https://render.com with your GitHub account.
2. **New → Blueprint**, pick the `medical-bill-checker` repository. Render reads
   `render.yaml` and asks for three values:
   - `DATABASE_URL`: the Neon connection string.
   - `BILLCHECKER_KEY`: an encryption key. Generate one with
     `python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`
     and **keep a copy** (password manager): saved bills can't be read without it.
   - `GEMINI_API_KEY`: your Gemini key. For real bills use a **paid** Gemini
     plan; the free plan may use what's sent to improve Google's products.
3. Click **Apply**. The first build takes several minutes. When it's live, copy
   the address, e.g. `https://clyvexa.onrender.com`. Opening
   `https://clyvexa.onrender.com/api/auth/session` should show `{"user":null}`.

`BILLCHECKER_ALLOWED_ORIGINS` in `render.yaml` lets the GitHub Pages site
(`https://shahet07.github.io`) use the server. A fork on another account
changes it to its own `https://<user>.github.io`.

## 3. Point the website at the server (GitHub)

1. In the repository: **Settings → Secrets and variables → Actions → Variables
   → New repository variable**: name `CLYVEXA_API_URL`, value the Render address
   (no trailing slash).
2. **Actions → Website (GitHub Pages) → Run workflow** (or push any change).

The website's app now uploads to your server. Remove the variable and re-run
the workflow to go back to the demo.

## Before inviting real users

- Fill in the bracketed placeholders in the privacy policy and terms
  (`frontend/src/app/privacy`, `terms`, `delete-account`) and have them reviewed.
- Use a paid AI plan (Gemini paid tier or Claude) for real bills.
