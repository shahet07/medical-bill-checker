"""Browser smoke test: drives the web UI in headless Chrome against a running server.

Covers: sign up, log out/in, history, account page, upload (bill + EOB), results, feedback, survey, editing a line,
letters (dispute, financial assistance, PDF), Spanish, a two-photo bill,
phone-sized dark mode, and deletion. Screenshots go to the output directory.
Uses the real LLM configured on the server.

    .venv/bin/uvicorn --factory billchecker.api:app_from_env --port 8765   # in another terminal
    .venv/bin/python scripts/make_fixtures.py
    .venv/bin/python scripts/ui_check.py /tmp/ui-shots fixtures
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT, FIX = Path(sys.argv[1]), Path(sys.argv[2])
URL = "http://127.0.0.1:8765/"
OUT.mkdir(parents=True, exist_ok=True)
errors = []


def watch(page):
    page.on("console", lambda m: errors.append("console %s: %s" % (m.type, m.text)) if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))


def results(page, timeout=240000):
    page.wait_for_selector("#results-view:not([hidden])", timeout=timeout)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1100, "height": 900}, locale="en-US")
    page = ctx.new_page()
    watch(page)
    page.goto(URL)

    # 0. Sign up (unique email per run), with research consent
    import time

    email = "smoke{}@example.com".format(int(time.time()))
    page.wait_for_selector("#auth-view:not([hidden])")
    page.click("#show-register")
    page.fill("#reg-email", email)
    page.fill("#reg-password", "correct horse battery")
    page.check("#reg-consent")
    page.click("#register-form button[type=submit]")
    page.wait_for_selector("#upload-view:not([hidden])")
    print("signed up:", page.inner_text("#user-email"))
    page.screenshot(path=str(OUT / "0_upload_logged_in.png"), full_page=True)

    # 1. Upload a scanned bill + EOB
    page.set_input_files("#bill-file", str(FIX / "denial_bill_scan.pdf"))
    page.set_input_files("#eob-file", str(FIX / "denial_eob.pdf"))
    page.click("#upload-button")
    results(page)
    print("flags:", page.locator(".flag h3").all_inner_texts())
    page.screenshot(path=str(OUT / "1_results.png"), full_page=True)

    # 2. Feedback and survey
    page.locator(".flag").first.get_by_role("button", name="Yes, a real problem").click()
    page.wait_for_selector(".flag .thanks:has-text('Thanks')")
    page.check('input[name="helpful"][value="4"]')
    page.check('input[name="most_useful"][value="letter"]')
    page.click("#survey-form button[type=submit]")
    page.wait_for_selector("#survey-thanks:not([hidden])")
    print("feedback + survey: ok")

    # 3. Letters: financial assistance and dispute PDF
    page.check("#kind-assistance")
    page.fill("#p-name", "Sam Example")
    page.click("#letter-form button[type=submit]")
    page.wait_for_selector("#letter-output:not([hidden])")
    print("assistance letter:", "charity care policy" in page.inner_text("#letter-text"))
    page.check("#kind-dispute")
    page.click("#letter-form button[type=submit]")
    with page.expect_download() as dl:
        page.click("#download-pdf")
    pdf = dl.value.path().read_bytes()
    print("dispute pdf:", pdf[:5] == b"%PDF-", dl.value.suggested_filename)
    print("appeal option shown:", page.is_visible("#appeal-choice"))

    # 4. Spanish
    page.click("#lang-toggle")
    # Explanations are rewritten in Spanish, so the results reload.
    page.wait_for_selector("#status-view:not([hidden])", timeout=10000)
    results(page)
    print("spanish heading:", page.inner_text("h1"), "|", page.locator(".flag h3").first.inner_text())
    print("spanish explanation:", page.locator(".line-expl").first.inner_text()[:80] if page.locator(".line-expl").count() else "(template)")
    page.screenshot(path=str(OUT / "2_spanish.png"), full_page=True)
    page.click("#lang-toggle")
    page.wait_for_selector("#status-view:not([hidden])", timeout=10000)
    results(page)

    # 5. Edit: remove the denied blood test line, which clears the denial flag
    page.click("#edit-lines")
    page.locator("#edit-rows .edit-row").nth(1).get_by_role("button", name="Remove").click()
    page.screenshot(path=str(OUT / "3_editing.png"), full_page=True)
    page.click("#edit-form button[type=submit]")
    # The old results stay on screen until the save lands, so wait for the edited view.
    page.wait_for_selector("#edited-note:not([hidden])", timeout=240000)
    print("after edit flags:", page.locator(".flag h3").all_inner_texts(), "| edited note:", page.is_visible("#edited-note"))

    # 6. Phone-sized dark mode of the same case
    mobile = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark")
    mobile.add_cookies(ctx.cookies())
    m = mobile.new_page()
    watch(m)
    m.goto(URL)
    m.evaluate("cid => sessionStorage.setItem('billchecker.case', cid)", page.evaluate("sessionStorage.getItem('billchecker.case')"))
    m.reload()
    results(m, 30000)
    print("mobile overflow:", m.evaluate("document.documentElement.scrollWidth > window.innerWidth"))
    m.screenshot(path=str(OUT / "4_mobile_dark.png"), full_page=True)

    # 7. History, log out and back in, reopen from history
    page.click("#new-bill")
    page.wait_for_selector("#history:not([hidden])")
    print("history:", page.locator(".history-item").all_inner_texts())
    page.click("#logout-button")
    page.wait_for_selector("#auth-view:not([hidden])")
    page.fill("#login-email", email)
    page.fill("#login-password", "correct horse battery")
    page.click("#login-form button[type=submit]")
    page.wait_for_selector("#history:not([hidden])")
    page.locator(".history-item").first.click()
    results(page, 30000)
    print("reopened from history after re-login:", page.locator(".flag").count(), "flags")

    # 8. Account page: consent off
    page.click("#account-button")
    page.wait_for_selector("#account-view:not([hidden])")
    page.uncheck("#account-consent")
    page.click("#consent-form button[type=submit]")
    page.wait_for_selector("#consent-saved:not([hidden])")
    page.screenshot(path=str(OUT / "6_account.png"), full_page=True)
    print("consent saved off")
    page.click("#account-back")
    page.wait_for_selector("#upload-view:not([hidden])")
    page.locator(".history-item").first.click()
    results(page, 30000)

    # 9. Delete the case
    page.once("dialog", lambda d: d.accept())
    page.click("#delete-case")
    page.wait_for_selector("#upload-view:not([hidden])")
    print("deleted:", page.inner_text("#error-banner"))

    # 10. Bill from two photos, in Spanish
    page.click("#lang-toggle")
    page.set_input_files("#bill-file", [str(FIX / "clean_bill_photo.jpg"), str(FIX / "clean_bill_photo.jpg")])
    page.click("#upload-button")
    results(page)
    print("two-photo bill in Spanish:", page.locator("#lines tbody tr").count(), "rows |", page.inner_text("#flags")[:60])
    page.screenshot(path=str(OUT / "5_two_photos_es.png"), full_page=True)
    page.once("dialog", lambda d: d.accept())
    page.click("#delete-case")
    page.wait_for_selector("#upload-view:not([hidden])")

    # 11. Delete the account
    page.click("#lang-toggle")
    page.click("#account-button")
    page.fill("#del-password", "correct horse battery")
    page.once("dialog", lambda d: d.accept())
    page.click("#delete-account-form button[type=submit]")
    page.wait_for_selector("#auth-view:not([hidden])")
    print("account deleted:", page.inner_text("#error-banner"))
    browser.close()

print("browser errors:", errors or "none")
