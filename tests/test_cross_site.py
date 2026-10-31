"""The GitHub Pages website calling the API on another site: CORS and header tokens."""

from test_api import clock, llm, make_client  # noqa: F401  (fixtures)

PAGES = "https://shahet07.github.io"
EVIL = "https://evil.example"
CREDS = {"email": "pat@example.com", "password": "correct horse battery"}


def cross_client(pg_dsn, llm, clock):  # noqa: F811
    return make_client(pg_dsn, llm, clock, allowed_origins=(PAGES,))


def test_preflight_from_allowed_site(pg_dsn, llm, clock):  # noqa: F811
    with cross_client(pg_dsn, llm, clock) as c:
        r = c.options("/api/auth/login", headers={"Origin": PAGES, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type, authorization"})
        assert r.status_code == 204
        assert r.headers["access-control-allow-origin"] == PAGES
        assert "authorization" in r.headers["access-control-allow-headers"].lower()
        other = c.options("/api/auth/login", headers={"Origin": EVIL, "Access-Control-Request-Method": "POST"})
        assert "access-control-allow-origin" not in other.headers


def test_allowed_site_logs_in_with_a_header_token(pg_dsn, llm, clock):  # noqa: F811
    with cross_client(pg_dsn, llm, clock) as c:
        r = c.post("/api/auth/register", json=CREDS, headers={"Origin": PAGES})
        assert r.status_code == 201 and r.headers["access-control-allow-origin"] == PAGES
        token = r.json()["session_token"]
        c.cookies.clear()  # another site's page never gets the cookie
        auth = {"Origin": PAGES, "Authorization": "Bearer " + token}
        assert c.get("/api/auth/session", headers=auth).json()["user"]["email"] == CREDS["email"]
        assert c.get("/api/cases", headers=auth).status_code == 200
        assert c.post("/api/auth/logout", headers=auth).status_code == 204
        assert c.get("/api/auth/session", headers=auth).json()["user"] is None  # token revoked


def test_same_site_login_gets_no_token(pg_dsn, llm, clock):  # noqa: F811
    with cross_client(pg_dsn, llm, clock) as c:
        body = c.post("/api/auth/register", json=CREDS).json()
        assert "session_token" not in body


def test_other_sites_still_refused(pg_dsn, llm, clock):  # noqa: F811
    with cross_client(pg_dsn, llm, clock) as c:
        r = c.post("/api/auth/register", json=CREDS, headers={"Origin": EVIL})
        assert r.status_code == 403 and "access-control-allow-origin" not in r.headers
    with make_client(pg_dsn, llm, clock) as c:  # nothing allowed by default
        assert c.post("/api/auth/register", json=CREDS, headers={"Origin": PAGES}).status_code == 403
