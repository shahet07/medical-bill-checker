"""Record a real session with the synthetic "denial" sample, for the website's demo mode.

Drives the app in Chrome against a running server (with a real LLM), saving
every /api response. The GitHub Pages build replays these in the browser
(frontend/src/lib/demo.ts), so the demo shows genuine output without a server.
The sample bill and EOB are synthetic: no real patient data.

    .venv/bin/uvicorn --factory billchecker.api:app_from_env --port 8765   # in another terminal
    .venv/bin/python scripts/make_fixtures.py
    .venv/bin/python scripts/capture_demo.py fixtures
"""

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

FIX = Path(sys.argv[1])
URL = "http://127.0.0.1:8765/app"
OUT = Path(__file__).resolve().parent.parent / "frontend" / "src" / "lib" / "demo-recording.json"

calls = []


def record(resp):
    u = urlsplit(resp.url)
    if not u.path.startswith("/api/"):
        return
    req = resp.request
    body = None
    if req.post_data and "json" in (req.headers.get("content-type") or ""):
        body = json.loads(req.post_data)
    try:
        data = resp.json()
    except Exception:
        data = None
    calls.append({"method": req.method, "path": u.path, "query": u.query, "status": resp.status, "request": body, "response": data})


def results(page, timeout=240000):
    page.wait_for_selector("#results-view:not([hidden])", timeout=timeout)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_context(viewport={"width": 1100, "height": 900}, locale="en-US").new_page()
    page.on("response", record)
    page.goto(URL)

    page.wait_for_selector("#auth-view:not([hidden])")
    page.click("#show-register")
    page.fill("#reg-email", "demo{}@example.com".format(int(time.time())))
    page.fill("#reg-password", "correct horse battery")
    page.click("#register-form button[type=submit]")
    page.wait_for_selector("#upload-view:not([hidden])")

    page.set_input_files("#bill-file", str(FIX / "denial_bill.pdf"))
    page.set_input_files("#eob-file", str(FIX / "denial_eob.pdf"))
    page.click("#upload-button")
    results(page)
    print("flags:", page.locator(".flag h3").all_inner_texts())

    for i in range(3):  # every example question
        page.locator("#ask-examples button").nth(i).click()
        page.wait_for_function("() => { const t = document.querySelector('#ask-text'); return t && t.textContent && !t.textContent.startsWith('Looking'); }", timeout=120000)

    page.fill("#p-name", "Sam Example")
    for kind in ("dispute", "itemized", "assistance", "plan", "appeal"):  # every letter type
        page.check("#kind-" + kind)
        if kind == "plan":
            page.fill("#p-monthly", "25")
        page.click("#letter-form button[type=submit]")
        page.wait_for_selector("#letter-output:not([hidden])")
        page.wait_for_timeout(2500)  # each kind replaces the letter in place

    page.click("#rehearse-start")
    page.wait_for_selector("#rehearse-log li")
    page.fill("#rehearse-input", "Hi, I'm calling about my bill from March 4. My insurer denied the blood test, but the bill still charges me for it.")
    page.click("#rehearse-form button[type=submit]")
    page.wait_for_function("() => document.querySelectorAll('#rehearse-log li').length >= 3", timeout=120000)
    page.click("#rehearse-score")
    page.wait_for_selector("#rehearse-result", timeout=120000)
    print("rehearsal scored")

    # Spanish: the explanations are rewritten, so the case is fetched again in Spanish
    page.click("#lang-toggle")
    page.wait_for_selector("#status-view:not([hidden])", timeout=10000)
    results(page)
    page.click("#lang-toggle")
    page.wait_for_selector("#status-view:not([hidden])", timeout=10000)
    results(page)

    page.click("#refunds-button")
    page.wait_for_selector("#refunds-view:not([hidden])")
    page.wait_for_timeout(1500)
    browser.close()

# Replace identifying values with fixed demo ones.
text = json.dumps(calls)
case_ids = sorted(set(re.findall(r'"case_id": "([^"]+)"', text)))
for n, cid in enumerate(case_ids):
    text = text.replace(cid, "demo-case" if n == 0 else "demo-case-%d" % n)
text = re.sub(r"demo\d+@example\.com", "demo@clyvexa.example", text)
text = text.replace(URL.rsplit("/", 1)[0], "https://clyvexa.example")  # links to the recording machine
OUT.write_text(json.dumps(json.loads(text), indent=1, ensure_ascii=False))
print("recorded", len(calls), "calls ->", OUT)
