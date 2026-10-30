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


@pytest.mark.parametrize("path, ctype", [("/static/app.js", "javascript"), ("/static/style.css", "text/css")])
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
    js = (WEB / "app.js").read_text()
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
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
const cases = JSON.parse(process.argv[2]);
const out = cases.map(([fn, arg]) => vm.runInContext(fn + "(" + JSON.stringify(arg) + ")", ctx));
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_money_and_date_formatting_in_js():
    cases = [
        ["money", "150.00"],
        ["money", "1250.5"],
        ["money", "-165.00"],
        ["money", "1234567.89"],
        ["money", "0.1"],
        ["money", None],
        ["shortDate", "2026-03-04"],
        ["shortDate", "2026-12-31"],
        ["shortDate", None],
    ]
    out = subprocess.run(
        ["node", "-e", NODE_HARNESS, str(WEB / "app.js"), json.dumps(cases)],
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
    ]
