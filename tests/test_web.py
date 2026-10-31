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


# --- Next.js frontend (static export) --------------------------------------------------------

import base64  # noqa: E402
import hashlib  # noqa: E402


def _fake_export(root):
    (root / "_next" / "static").mkdir(parents=True)
    (root / "_next" / "static" / "app.js").write_text("console.log('next')")
    (root / "index.html").write_text(
        '<!doctype html><html><head><script src="/_next/static/app.js" async=""></script></head>'
        "<body><div id=app></div><script>self.__next_f=[1]</script></body></html>"
    )
    return root


def test_next_frontend_served_with_hash_pinned_csp(pg_dsn, llm, clock, tmp_path):  # noqa: F811
    from test_api import make_client

    with make_client(pg_dsn, llm, clock, frontend_dir=_fake_export(tmp_path / "out")) as c:
        r = c.get("/")
        assert "self.__next_f" in r.text
        digest = base64.b64encode(hashlib.sha256(b"self.__next_f=[1]").digest()).decode()
        csp = r.headers["content-security-policy"]
        assert "script-src 'self' 'sha256-{}'".format(digest) in csp
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
        assert c.get("/_next/static/app.js").status_code == 200
        assert c.get("/static/app.js").status_code == 200  # original page's assets still available


def test_missing_build_falls_back_to_original_page(pg_dsn, llm, clock, tmp_path):  # noqa: F811
    from test_api import make_client

    with make_client(pg_dsn, llm, clock, frontend_dir=tmp_path / "nothing-here") as c:
        r = c.get("/")
        assert '<script src="/static/app.js"' in r.text
        assert "sha256-" not in r.headers["content-security-policy"]
        assert '<script src="/static/app.js"' in c.get("/app").text


def test_inline_script_hashes_cover_every_page(tmp_path):
    from billchecker.api import inline_script_hashes

    root = _fake_export(tmp_path / "out")
    (root / "404.html").write_text("<script>other()</script><script src=x.js></script>")
    assert len(inline_script_hashes(root)) == 2


def test_in_browser_models_are_served(pg_dsn, llm, clock, tmp_path):  # noqa: F811
    from test_api import make_client

    root = _fake_export(tmp_path / "out")
    (root / "models" / "photo-quality").mkdir(parents=True)
    (root / "models" / "photo-quality" / "manifest.json").write_text('{"version": 1}')
    with make_client(pg_dsn, llm, clock, frontend_dir=root) as c:
        r = c.get("/models/photo-quality/manifest.json")
        assert r.status_code == 200 and r.json() == {"version": 1}
        assert "content-security-policy" in r.headers


FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


@pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules" / "@tensorflow" / "tfjs").is_dir(),
    reason="needs node and frontend/node_modules (CI runs this in the frontend job)",
)
def test_tfjs_model_matches_keras():
    r = subprocess.run(["node", "scripts/tfjs-parity.mjs"], cwd=FRONTEND, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_root_icons_served_but_nothing_else(pg_dsn, llm, clock, tmp_path):  # noqa: F811
    from test_api import make_client

    root = _fake_export(tmp_path / "out")
    (root / "icon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (root / "notes.txt").write_text("private")
    with make_client(pg_dsn, llm, clock, frontend_dir=root) as c:
        assert c.get("/icon.svg").status_code == 200
        assert c.get("/notes.txt").status_code == 404
        assert c.get("/index.html").status_code == 404
        assert c.get("/api/auth/session").status_code == 200  # API routes are unaffected


def test_site_pages_served_by_name(pg_dsn, llm, clock, tmp_path):  # noqa: F811
    from test_api import make_client

    root = _fake_export(tmp_path / "out")
    for page in ("app", "verify", "privacy", "terms", "delete-account"):
        (root / (page + ".html")).write_text("<html><body>{}</body></html>".format(page))
    (root / "_not-found.html").write_text("nf")
    with make_client(pg_dsn, llm, clock, frontend_dir=root) as c:
        for page in ("app", "verify", "privacy", "terms", "delete-account"):
            r = c.get("/" + page)
            assert r.status_code == 200 and page in r.text, page
            assert "content-security-policy" in r.headers
        assert c.get("/_not-found").status_code == 404
        assert c.get("/index").status_code == 404
