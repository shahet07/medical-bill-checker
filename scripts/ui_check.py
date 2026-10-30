"""Browser smoke test: drives the web UI in headless Chrome against a running server.

Uploads the synthetic denial bill (scan) and EOB, waits for results, creates a
letter, checks a phone-sized dark-mode view, then deletes the case. Screenshots
go to the output directory. Uses the real LLM configured on the server.

    .venv/bin/uvicorn --factory billchecker.api:app_from_env --port 8765   # in another terminal
    .venv/bin/python scripts/make_fixtures.py
    .venv/bin/python scripts/ui_check.py /tmp/ui-shots fixtures
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
SP, FIX = sys.argv[1], sys.argv[2]
Path(SP).mkdir(parents=True, exist_ok=True)
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1100, "height": 900})
    page.on("console", lambda m: errors.append("console %s: %s" % (m.type, m.text)) if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
    page.goto("http://127.0.0.1:8765/")
    page.screenshot(path=SP + "/ui_1_upload.png", full_page=True)
    page.set_input_files("#bill-file", FIX + "/denial_bill_scan.pdf")
    page.set_input_files("#eob-file", FIX + "/denial_eob.pdf")
    page.click("#upload-button")
    page.wait_for_selector("#status-view:not([hidden])", timeout=30000)
    page.screenshot(path=SP + "/ui_2_status.png")
    page.wait_for_selector("#results-view:not([hidden])", timeout=240000)
    page.screenshot(path=SP + "/ui_3_results.png", full_page=True)
    print("flags shown:", page.locator(".flag h3").all_inner_texts())
    page.uncheck("#flags input[data-flag-id^='balance_mismatch']")
    page.fill("#p-name", "Sam Example")
    page.fill("#p-address", "12 Elm Street\nSpringfield, IL 62701")
    page.fill("#p-account", "00098765432")
    page.click("#letter-form button[type=submit]")
    page.wait_for_selector("#letter-output:not([hidden])")
    letter = page.inner_text("#letter-text")
    print("letter has account:", "Account number: 00098765432" in letter, "| balance item excluded:", "Amount due does not match" not in letter)
    page.screenshot(path=SP + "/ui_4_letter.png", full_page=True)
    mobile = browser.new_page(viewport={"width": 390, "height": 844}, color_scheme="dark")
    mobile.context.add_cookies(page.context.cookies())
    mobile.goto("http://127.0.0.1:8765/")
    mobile.evaluate("cid => sessionStorage.setItem('billchecker.case', cid)", page.evaluate("sessionStorage.getItem('billchecker.case')"))
    mobile.reload()
    mobile.wait_for_selector("#results-view:not([hidden])", timeout=30000)
    print("mobile horizontal overflow:", mobile.evaluate("document.documentElement.scrollWidth > window.innerWidth"))
    mobile.screenshot(path=SP + "/ui_5_mobile_dark.png", full_page=True)
    page.once("dialog", lambda d: d.accept())
    page.click("#delete-case")
    page.wait_for_selector("#upload-view:not([hidden])")
    print("after delete banner:", page.inner_text("#error-banner"))
    browser.close()
print("browser errors:", errors or "none")
