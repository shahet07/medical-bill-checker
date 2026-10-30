import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_api import client, clock, llm  # noqa: F401  (fixtures)

WEB = Path(__file__).resolve().parent.parent / "src" / "billchecker" / "web"


def test_index_served_with_csp(client):  # noqa: F811
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe" not in csp
    assert '<script src="/static/app.js"' in r.text


@pytest.mark.parametrize(
    "path, ctype", [("/static/app.js", "javascript"), ("/static/i18n.js", "javascript"), ("/static/style.css", "text/css")]
)
def test_static_assets(client, path, ctype):  # noqa: F811
    r = client.get(path)
    assert r.status_code == 200 and ctype in r.headers["content-type"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_no_inline_script_style_or_handlers():
    html = (WEB / "index.html").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "inline <script> would be blocked by CSP"
    assert "<style" not in html and " style=" not in html
    assert not re.search(r"\son[a-z]+=", html), "inline event handlers would be blocked by CSP"
    assert "http://" not in html and "https://" not in html, "no third-party resources"


def test_js_never_inserts_html():
    js = (WEB / "app.js").read_text() + (WEB / "i18n.js").read_text()
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert banned not in js, banned


def test_every_element_id_used_by_js_exists():
    html = (WEB / "index.html").read_text()
    js = (WEB / "app.js").read_text()
    ids = set(re.findall(r'id="([^"]+)"', html))
    used = set(re.findall(r'\$\("#([a-zA-Z0-9-]+)', js)) | set(re.findall(r'"([a-z]+-view)"', js))
    assert used - ids == set()


NODE_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");
const ctx = { document: { addEventListener() {} }, window: {}, sessionStorage: {}, console };
vm.createContext(ctx);
const dir = process.argv[1];
vm.runInContext(fs.readFileSync(dir + "/i18n.js", "utf8") + "\n" + fs.readFileSync(dir + "/app.js", "utf8"), ctx);
const cases = JSON.parse(process.argv[2]);
const out = cases.map(([lang, fn, arg]) => vm.runInContext("LANG = " + JSON.stringify(lang) + "; " + fn + "(" + JSON.stringify(arg) + ")", ctx));
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_money_and_date_formatting_in_js():
    cases = [
        ["en", "money", "150.00"],
        ["en", "money", "1250.5"],
        ["en", "money", "-165.00"],
        ["en", "money", "1234567.89"],
        ["en", "money", "0.1"],
        ["en", "money", None],
        ["en", "shortDate", "2026-03-04"],
        ["en", "shortDate", "2026-12-31"],
        ["en", "shortDate", None],
        ["es", "shortDate", "2026-03-04"],
        ["es", "t", "rule_duplicate_line"],
        ["fr", "t", "rule_duplicate_line"],
    ]
    out = subprocess.run(
        ["node", "-e", NODE_HARNESS, str(WEB), json.dumps(cases)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert json.loads(out) == [
        "$150.00",
        "$1,250.50",
        "−$165.00",
        "$1,234,567.89",
        "$0.10",
        "—",
        "Mar 4, 2026",
        "Dec 31, 2026",
        "—",
        "4 mar 2026",
        "Posible cargo duplicado",
        "Possible duplicate charge",  # unknown language falls back to English
    ]


# --- Translations ---------------------------------------------------------------------------

I18N_DUMP = r"""
const vm = require("vm");
const fs = require("fs");
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8") + "\n;this.out = {STATIC_ES, STRINGS, GLOSSARY, SERVER_ERRORS_ES};", ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""


@pytest.fixture(scope="module")
def i18n():
    if shutil.which("node") is None:
        pytest.skip("node not installed")
    out = subprocess.run(["node", "-e", I18N_DUMP, str(WEB / "i18n.js")], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_every_tagged_text_has_spanish(i18n):
    html = (WEB / "index.html").read_text()
    keys = set(re.findall(r'data-i18n(?:-placeholder)?="([^"]+)"', html))
    assert keys - set(i18n["STATIC_ES"]) == set()


def test_english_and_spanish_have_the_same_messages(i18n):
    assert set(i18n["STRINGS"]["en"]) == set(i18n["STRINGS"]["es"])
    assert len(i18n["GLOSSARY"]["en"]) == len(i18n["GLOSSARY"]["es"])


def test_every_message_used_by_js_exists(i18n):
    js = (WEB / "app.js").read_text()
    # Keys ending in "_" are prefixes completed at runtime; the full keys are listed below.
    used = {k for k in re.findall(r'\bt\("([a-z_0-9]+)"', js) if not k.endswith("_")}
    used |= {"rule_" + r for r in ("duplicate_line", "balance_mismatch", "billed_after_denial", "network_mismatch",
                                   "no_itemization", "not_on_eob", "charge_mismatch", "payment_not_applied")}
    used |= {"conf_high", "conf_medium", "conf_low", "verdict_correct", "verdict_incorrect", "verdict_unsure"}
    used |= {"failed_" + c for c in ("unreadable", "llm_unavailable", "expired", "internal_error")}
    assert used - set(i18n["STRINGS"]["en"]) == set()


def test_rule_titles_cover_every_rule(i18n):
    from typing import get_args

    from billchecker.models import RuleName

    assert {"rule_" + r for r in get_args(RuleName)} <= set(i18n["STRINGS"]["es"])


def test_server_error_codes_have_spanish(i18n):
    api = (Path(__file__).resolve().parent.parent / "src" / "billchecker" / "api.py").read_text()
    ingest = (Path(__file__).resolve().parent.parent / "src" / "billchecker" / "ingest.py").read_text()
    auth = (Path(__file__).resolve().parent.parent / "src" / "billchecker" / "auth.py").read_text()
    codes = set(re.findall(r'_error\(\d+, "([a-z_]+)"', api)) | set(re.findall(r'IngestError\(\s*"([a-z_]+)"', ingest))
    codes |= set(re.findall(r'AuthError\(\s*"([a-z_]+)"', auth)) | set(re.findall(r'"error": "([a-z_]+)"', api))
    codes -= {"expired"}  # only shown via the failed-case screen, which has its own text
    assert codes - set(i18n["SERVER_ERRORS_ES"]) == set()
