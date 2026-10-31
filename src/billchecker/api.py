"""HTTP API.

Every case belongs to a logged-in user (email + password). The login cookie
is HttpOnly, Secure, SameSite=Strict, and holds a random token stored only as
a hash. Another user's IDs return 404, the same as IDs that do not exist.
State-changing requests from another site's pages are refused (Origin check).
Patient details for letters are used once to render the letter and never stored.

Run locally:
    scripts/dev_db.sh start
    export DATABASE_URL=postgresql://billchecker@127.0.0.1:54329/billchecker
    export BILLCHECKER_KEY=$(python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())")
    export GEMINI_API_KEY=...
    .venv/bin/uvicorn --factory billchecker.api:app_from_env
"""

import logging
import os
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Deque, Dict, List, Literal, Optional, Tuple

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import auth
from .auth import AuthError
from .ingest import MAX_BYTES, MAX_FILES, IngestError, ingest_many, sniff_type
from .letters import (
    MAX_NOTE_CHARS,
    Patient,
    dispute,
    financial_assistance,
    insurer_appeal,
    itemized_request,
    payment_plan,
)
from .letters_pdf import render_pdf
from .llm import JsonLLM, make_llm
from .models import Bill, Eob, Flag, Money
from .pipeline import CaseRunner
from .rag import MAX_QUESTION_CHARS, GeminiEmbedder, KnowledgeBase, answer_question
from .radar import DEFAULT_K, normalize_provider, present
from .refunds import Payment, Statement, episode_out, find_refunds, refund_letter
from .photo_quality import check_pages
from .packet import build_payload, new_packet_id, public_key_b64, sha256_hex, sign, signing_key
from .packet import verify as verify_packet
from .rehearsal import MAX_TURNS, Turn, opening, rep_reply, score_call, suggested_opener
from .reference import Reference, load_pairs, load_prices
from .store import Store, UserRow, load_key, pack_files

log = logging.getLogger("billchecker.api")

WEB_DIR = Path(__file__).parent / "web"
# The Next.js frontend, built with `npm run build` in frontend/ (static export).
DEFAULT_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "out"
# Same-origin only, no inline style, no framing, no third-party anything. Inline
# scripts are allowed only by exact hash (the few that Next.js writes into its HTML).
CSP_TEMPLATE = (
    "default-src 'self'; script-src 'self'{hashes}; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; form-action 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'"
)
CSP = CSP_TEMPLATE.format(hashes="")
_INLINE_SCRIPT = re.compile(rb"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)


def inline_script_hashes(html_dir: Path) -> List[str]:
    """CSP source expressions for every inline <script> in the built HTML files."""
    import base64
    import hashlib

    out = set()
    for page in html_dir.rglob("*.html"):
        for body in _INLINE_SCRIPT.findall(page.read_bytes()):
            out.add("'sha256-{}'".format(base64.b64encode(hashlib.sha256(body).digest()).decode()))
    return sorted(out)
SESSION_COOKIE = "bc_session"
MIME = {"pdf": "application/pdf", "png": "image/png", "jpeg": "image/jpeg", "heic": "image/heic"}
MAX_EOBS = 5
# action -> (max requests, window in seconds). Per user, except login/register: per IP address.
DEFAULT_LIMITS = {
    "upload": (20, 3600),
    "case": (10, 3600),
    "letter": (60, 3600),
    "confirm": (20, 3600),
    "feedback": (100, 3600),
    "login": (20, 900),
    "register": (5, 3600),
    "account": (10, 3600),
    "ask": (30, 3600),
    "rehearse": (150, 3600),
    "verify": (120, 3600),
    "payments": (60, 3600),
}


@dataclass
class Settings:
    database_url: str
    key: bytes
    llm: JsonLLM
    reference: Reference = field(default_factory=Reference)
    knowledge: Optional[KnowledgeBase] = None  # default: keyword search over the bundled guides
    radar_k: int = DEFAULT_K  # distinct reporters needed before a radar pattern is shown
    # Built Next.js frontend to serve at "/". None or missing: serve the original page in web/.
    frontend_dir: Optional[Path] = None
    secure_cookies: bool = True
    inline_jobs: bool = False
    cleanup_interval: Optional[float] = 3600.0  # seconds; None disables the background sweep
    limits: Dict[str, Tuple[int, int]] = field(default_factory=lambda: dict(DEFAULT_LIMITS))
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    today: Callable[[], date] = lambda: date.today()


# --- Request bodies -------------------------------------------------------------------


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Register(_Body):
    email: str = Field(max_length=254)
    password: str = Field(max_length=auth.MAX_PASSWORD)
    research_consent: bool = False
    radar_consent: bool = False


class Login(_Body):
    email: str = Field(max_length=254)
    password: str = Field(max_length=auth.MAX_PASSWORD)


class ChangePassword(_Body):
    current_password: str = Field(max_length=auth.MAX_PASSWORD)
    new_password: str = Field(max_length=auth.MAX_PASSWORD)


class Consent(_Body):
    research_consent: bool


class RadarConsent(_Body):
    radar_consent: bool


class DeleteAccount(_Body):
    password: str = Field(max_length=auth.MAX_PASSWORD)


class CreateCase(_Body):
    bill_upload_id: str
    eob_upload_ids: List[str] = Field(default_factory=list, max_length=MAX_EOBS)
    eob_upload_id: Optional[str] = None  # single-EOB shorthand
    language: Literal["en", "es"] = "en"  # language of the explanations


class ConfirmTotals(_Body):
    billed: Optional[Money] = None
    patient_balance: Optional[Money] = None


class PatientIn(_Body):
    name: str = Field(min_length=1, max_length=200)
    address_lines: List[str] = Field(default_factory=list, max_length=4)
    phone: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=200)
    account_number: Optional[str] = Field(default=None, max_length=50)
    member_id: Optional[str] = Field(default=None, max_length=50)


class LineEdit(_Body):
    line_id: Optional[str] = None  # the original line this edits; None for a new line
    service_date: Optional[date] = None
    description: str = Field(min_length=1, max_length=300)
    code: Optional[str] = Field(default=None, max_length=20)
    units: Optional[Decimal] = Field(default=None, ge=0, le=10000)
    charge: Money


class TotalsEdit(_Body):
    billed: Optional[Money] = None
    adjustments: Optional[Money] = None
    patient_balance: Optional[Money] = None


class BillEdit(_Body):
    line_items: List[LineEdit] = Field(max_length=200)
    totals: TotalsEdit


def guess_code_type(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    c = code.strip().upper()
    if re.match(r"^\d{5}([-\s]?[A-Z0-9]{2})*$", c):
        return "CPT"
    if re.match(r"^[A-Z]\d{4}([-\s]?[A-Z0-9]{2})*$", c):
        return "HCPCS"
    if re.match(r"^\d{3,4}$", c):
        return "REV"
    return "OTHER"


def apply_edit(bill: Bill, edit: BillEdit) -> Bill:
    """Rebuild the bill from the user's corrected lines and totals.

    Unchanged lines keep their source text from the document. Changed or new
    lines get source text that says the user entered them, so evidence never
    presents the user's correction as something printed on the bill.
    """
    originals = {li.line_id: li for li in bill.line_items}
    items = []
    for n, e in enumerate(edit.line_items, 1):
        code = e.code.strip() if e.code and e.code.strip() else None
        orig = originals.get(e.line_id) if e.line_id else None
        fields = dict(service_date=e.service_date, description=e.description.strip(), code=code, units=e.units, charge=e.charge)
        unchanged = orig is not None and all(getattr(orig, k) == v for k, v in fields.items())
        if unchanged:
            items.append(orig.model_copy(update={"line_id": "L{}".format(n)}))
            continue
        text = "Entered by you: {} {} {}".format(
            e.service_date.isoformat() if e.service_date else "", code or "", e.description.strip()
        )
        items.append(
            dict(
                fields,
                line_id="L{}".format(n),
                code_type=orig.code_type if orig is not None and orig.code == code else guess_code_type(code),
                source_page=orig.source_page if orig is not None else 1,
                source_text=" ".join(text.split()) + " " + str(e.charge),
            )
        )
    data = bill.model_dump(mode="json")
    data["line_items"] = [i.model_dump(mode="json") if hasattr(i, "model_dump") else i for i in items]
    data["totals"] = dict(data["totals"], **edit.totals.model_dump(mode="json"))
    data["itemized"] = bool(items) or bill.itemized
    data["extraction_confidence"] = bill.extraction_confidence
    return Bill.model_validate(data)


class FlagFeedback(_Body):
    flag_id: str
    verdict: Literal["correct", "incorrect", "unsure"]


class Survey(_Body):
    helpful: int = Field(ge=1, le=5)
    most_useful: Literal["explanation", "letter", "both", "neither"]


class Question(_Body):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    case_id: Optional[str] = None  # answer with this bill's data in mind
    language: Literal["en", "es"] = "en"


class Rehearsal(_Body):
    counterpart: Literal["billing_office", "insurer"] = "billing_office"
    turns: List[Turn] = Field(default_factory=list, max_length=MAX_TURNS)
    language: Literal["en", "es"] = "en"


class PaymentIn(_Body):
    case_id: str  # the bill (visit) this payment was for
    amount: Money = Field(gt=0)
    paid_on: date
    note: str = Field(default="", max_length=100)


class RefundLetter(_Body):
    episode_id: str = Field(max_length=32)
    patient: PatientIn
    note: Optional[str] = Field(default=None, max_length=MAX_NOTE_CHARS)
    format: Literal["json", "pdf"] = "json"


class LanguageChange(_Body):
    language: Literal["en", "es"]


class LetterRequest(_Body):
    kind: Literal["itemized_request", "dispute", "financial_assistance", "payment_plan", "insurer_appeal"]
    patient: PatientIn
    monthly_amount: Optional[Money] = None  # payment_plan only
    flag_ids: Optional[List[str]] = None  # dispute only; default all flags
    note: Optional[str] = Field(default=None, max_length=MAX_NOTE_CHARS)
    format: Literal["json", "pdf"] = "json"


# --- Helpers ----------------------------------------------------------------------------


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": code, "message": message})


class RateLimiter:
    def __init__(self, limits: Dict[str, Tuple[int, int]]):
        self.limits = limits
        self._hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, who: str, action: str) -> None:
        count, window = self.limits[action]
        now = time.monotonic()
        with self._lock:
            hits = self._hits[(who, action)]
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= count:
                raise _error(429, "rate_limited", "Too many requests. Please wait a while and try again.")
            hits.append(now)


# --- App ------------------------------------------------------------------------------


def create_app(settings: Settings) -> FastAPI:
    store = Store(settings.database_url, settings.key, now=settings.now)
    runner = CaseRunner(store, settings.llm, inline=settings.inline_jobs, reference=settings.reference)
    knowledge = settings.knowledge or KnowledgeBase()
    packet_key = signing_key(settings.key)
    packet_public = public_key_b64(packet_key)
    limiter = RateLimiter(settings.limits)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = threading.Event()
        if settings.cleanup_interval:

            def sweep() -> None:
                while not stop.wait(settings.cleanup_interval):
                    try:
                        store.cleanup()
                    except Exception as exc:
                        log.error("cleanup failed with %s", type(exc).__name__)

            threading.Thread(target=sweep, name="cleanup", daemon=True).start()
        store.cleanup()
        yield
        stop.set()
        runner.shutdown()
        store.close()

    app = FastAPI(title="Medical Bill Checker", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.runner = runner

    frontend = settings.frontend_dir if settings.frontend_dir and (settings.frontend_dir / "index.html").is_file() else None
    csp = CSP_TEMPLATE.format(hashes="".join(" " + h for h in inline_script_hashes(frontend))) if frontend else CSP
    app.state.frontend = frontend

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # Refuse state-changing API calls made from another site's pages.
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and origin.split("://", 1)[-1] != request.headers.get("host", ""):
                return JSONResponse({"detail": {"error": "bad_origin", "message": "Request refused."}}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers["Content-Security-Policy"] = csp
        return response

    @app.get("/", include_in_schema=False)
    def index():
        page = (frontend or WEB_DIR) / "index.html"
        return FileResponse(page, headers={"Cache-Control": "no-cache"})

    if frontend:
        # Hashed, immutable build assets.
        app.mount("/_next", StaticFiles(directory=frontend / "_next"), name="next")
        if (frontend / "models").is_dir():
            # In-browser models (TensorFlow.js weights), fetched only when someone picks a photo.
            app.mount("/models", StaticFiles(directory=frontend / "models"), name="models")
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    def current_user(request: Request) -> UserRow:
        token = request.cookies.get(SESSION_COOKIE)
        user = store.session_user(token) if token else None
        if user is None:
            raise _error(401, "login_required", "Please log in.")
        return user

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def start_session(response: Response, user: UserRow) -> None:
        token = store.create_session(user.user_id)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=int(store.session_ttl.total_seconds()),
            httponly=True,
            secure=settings.secure_cookies,
            samesite="strict",
        )

    def end_session(response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE, secure=settings.secure_cookies, httponly=True, samesite="strict")

    def auth_error(exc: AuthError) -> HTTPException:
        status = {"email_taken": 409, "bad_login": 401, "bad_password": 401, "locked": 429}.get(exc.code, 422)
        return _error(status, exc.code, exc.message)

    def me(user: UserRow) -> dict:
        return {
            "email": user.email,
            "research_consent": user.research_consent,
            "radar_consent": user.radar_consent,
            "created_at": user.created_at.isoformat(),
        }

    def own_case(case_id: str, user_id: str):
        case = store.get_case(user_id, case_id)
        if case is None:
            raise _error(404, "not_found", "Case not found. It may have expired.")
        return case

    # --- Accounts -----------------------------------------------------------------------------

    @app.post("/api/auth/register", status_code=201)
    def register(body: Register, request: Request, response: Response):
        limiter.check(client_ip(request), "register")
        try:
            user = auth.register(store, body.email, body.password, body.research_consent)
        except AuthError as exc:
            raise auth_error(exc)
        if body.radar_consent:
            store.set_radar_consent(user.user_id, True)
            user = store.get_user(user.user_id)
        start_session(response, user)
        store.record_event("signup", user.user_id, research_consent=user.research_consent)
        return me(user)

    @app.post("/api/auth/login")
    def login(body: Login, request: Request, response: Response):
        limiter.check(client_ip(request), "login")
        try:
            user = auth.login(store, body.email, body.password)
        except AuthError as exc:
            raise auth_error(exc)
        old = request.cookies.get(SESSION_COOKIE)
        if old:
            store.delete_session(old)
        start_session(response, user)
        store.record_event("login", user.user_id)
        return me(user)

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request):
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            store.delete_session(token)
        response = Response(status_code=204)
        end_session(response)
        return response

    @app.get("/api/auth/session")
    def session_status(request: Request):
        """Who is logged in, if anyone. Unlike /me, a logged-out browser gets 200, not an error."""
        token = request.cookies.get(SESSION_COOKIE)
        user = store.session_user(token) if token else None
        return {"user": me(user) if user else None}

    @app.get("/api/auth/me")
    def whoami(user: UserRow = Depends(current_user)):
        return me(user)

    @app.post("/api/auth/password", status_code=204)
    def change_password(body: ChangePassword, request: Request, user: UserRow = Depends(current_user)):
        limiter.check(user.user_id, "account")
        try:
            auth.change_password(
                store, user, body.current_password, body.new_password, keep_session=request.cookies.get(SESSION_COOKIE)
            )
        except AuthError as exc:
            raise auth_error(exc)
        store.record_event("password_changed", user.user_id)
        return Response(status_code=204)

    @app.put("/api/auth/consent")
    def set_consent(body: Consent, user: UserRow = Depends(current_user)):
        store.set_consent(user.user_id, body.research_consent)
        if not body.research_consent:
            for case in store.list_cases(user.user_id):
                store.delete_research(case.case_id)
        store.record_event("consent_changed", user.user_id, research_consent=body.research_consent)
        return me(store.get_user(user.user_id))

    @app.put("/api/auth/radar-consent")
    def set_radar_consent(body: RadarConsent, user: UserRow = Depends(current_user)):
        store.set_radar_consent(user.user_id, body.radar_consent)  # withdrawing deletes this user's reports
        store.record_event("radar_consent_changed", user.user_id, radar_consent=body.radar_consent)
        return me(store.get_user(user.user_id))

    @app.delete("/api/auth/account", status_code=204)
    def delete_account(body: DeleteAccount, user: UserRow = Depends(current_user)):
        limiter.check(user.user_id, "account")
        if not auth.verify_password(user.password_hash, body.password):
            raise _error(401, "bad_password", "Your password is incorrect.")
        store.record_event("account_deleted", user.user_id)
        store.delete_user(user.user_id)
        response = Response(status_code=204)
        end_session(response)
        return response

    # --- Cases --------------------------------------------------------------------------------

    @app.get("/api/cases")
    def list_cases(user: UserRow = Depends(current_user)):
        out = []
        for case in store.list_cases(user.user_id):
            result = store.get_result(case.case_id) or {}
            bill = result.get("bill") or {}
            totals = bill.get("totals") or {}
            out.append(
                {
                    "case_id": case.case_id,
                    "status": case.status,
                    "created_at": case.created_at,
                    "expires_at": case.expires_at,
                    "provider_name": bill.get("provider_name"),
                    "statement_date": bill.get("statement_date"),
                    "amount_due": totals.get("patient_balance"),
                    "flag_count": len(result.get("flags") or []),
                }
            )
        return {"cases": out}

    @app.post("/api/uploads", status_code=201)
    def upload(kind: Literal["bill", "eob"] = Form(...), file: List[UploadFile] = File(...), user: UserRow = Depends(current_user)):
        """One document, as one file or several (e.g. a photo of each page)."""
        limiter.check(user.user_id, "upload")
        if len(file) > MAX_FILES:
            raise _error(422, "too_many_files", "Please upload at most 10 files at a time.")
        files, total = [], 0
        for f in file:
            data = f.file.read(MAX_BYTES + 1 - total)
            total += len(data)
            if total > MAX_BYTES:
                raise _error(422, "too_large", "These files add up to more than 20 MB. Please upload smaller files.")
            files.append(data)
        try:
            doc = ingest_many(files)  # validates type, size, pages, readability up front
        except IngestError as exc:
            raise _error(422, exc.code, exc.message)
        mime = MIME[sniff_type(files[0])] if len(files) == 1 else "multipart/mixed"
        row = store.add_upload(user.user_id, kind, mime, len(doc.pages), pack_files(files), [sha256_hex(f) for f in files])
        # Photo quality: a fast local model, so a bad photo can be retaken before any LLM call. Warns only.
        quality = check_pages(doc.pages)
        flagged = [q for q in quality if q["issues"]]
        store.record_event("upload", user.user_id, kind=kind, pages=row.page_count, files=len(files), quality_warnings=len(flagged))
        return {
            "upload_id": row.upload_id,
            "kind": kind,
            "page_count": row.page_count,
            "expires_at": row.expires_at,
            "quality": quality,
        }

    @app.post("/api/cases", status_code=201)
    def create_case(body: CreateCase, user: UserRow = Depends(current_user)):
        limiter.check(user.user_id, "case")
        bill = store.get_upload(user.user_id, body.bill_upload_id)
        if bill is None or bill.kind != "bill":
            raise _error(404, "not_found", "Bill upload not found. It may have expired.")
        eob_ids = list(dict.fromkeys(body.eob_upload_ids + ([body.eob_upload_id] if body.eob_upload_id else [])))
        if len(eob_ids) > MAX_EOBS:
            raise _error(422, "too_many_eobs", "Please add at most 5 EOBs to one bill.")
        for eob_id in eob_ids:
            eob = store.get_upload(user.user_id, eob_id)
            if eob is None or eob.kind != "eob":
                raise _error(404, "not_found", "EOB upload not found. It may have expired.")
        case = store.add_case(user.user_id, body.bill_upload_id, eob_ids, body.language)
        store.record_event("case_created", user.user_id, eobs=len(eob_ids), language=body.language)
        runner.submit(case.case_id)
        case = store.get_case(user.user_id, case.case_id)
        return {"case_id": case.case_id, "status": case.status}

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str, user: UserRow = Depends(current_user)):
        case = own_case(case_id, user.user_id)
        out = {
            "case_id": case.case_id,
            "status": case.status,
            "error_code": case.error_code,
            "expires_at": case.expires_at,
            "language": case.language,
        }
        result = store.get_result(case.case_id) if case.status in ("ready", "needs_confirmation", "failed") else None
        if result:
            out.update(
                {k: result[k] for k in ("bill", "eob", "eob_status", "flags", "explanations", "problems", "warnings")}
            )
            out["user_edited"] = bool(result.get("user_edited"))
            out["price_context"] = result.get("price_context") or {}
            out["prices_label"] = result.get("prices_label")
            provider_key = normalize_provider((result.get("bill") or {}).get("provider_name"))
            out["radar"] = present(store.radar_patterns(provider_key, settings.radar_k), settings.radar_k) if provider_key else []
            out["error_message"] = result.get("error_message")
        return out

    @app.post("/api/cases/{case_id}/confirm")
    def confirm(case_id: str, body: ConfirmTotals, user: UserRow = Depends(current_user)):
        limiter.check(user.user_id, "confirm")
        case = own_case(case_id, user.user_id)
        if case.status != "needs_confirmation":
            raise _error(409, "wrong_status", "This case does not need confirmation.")
        result = store.get_result(case.case_id)
        bill = Bill.model_validate(result["bill"])
        totals = bill.totals.model_copy(update={"billed": body.billed, "patient_balance": body.patient_balance})
        bill = bill.model_copy(update={"totals": totals})
        store.put_result(case.case_id, dict(result, bill=bill.model_dump(mode="json"), confirmed=True, problems=[]))
        store.set_status(case.case_id, "queued")
        runner.submit(case.case_id)
        return {"case_id": case.case_id, "status": store.get_case(user.user_id, case.case_id).status}

    @app.put("/api/cases/{case_id}/bill")
    def edit_bill(case_id: str, body: BillEdit, user: UserRow = Depends(current_user)):
        limiter.check(user.user_id, "confirm")
        case = own_case(case_id, user.user_id)
        if case.status not in ("ready", "needs_confirmation"):
            raise _error(409, "wrong_status", "The bill can be edited once it has been read.")
        result = store.get_result(case.case_id)
        try:
            bill = apply_edit(Bill.model_validate(result["bill"]), body)
        except ValueError:
            raise _error(422, "invalid_edit", "Some of the corrected values are not valid.")
        result = dict(result, bill=bill.model_dump(mode="json"), confirmed=True, user_edited=True, problems=[])
        store.record_event("bill_edited", user.user_id)
        store.put_result(case.case_id, dict(result, flags=[], explanations=None))
        store.set_status(case.case_id, "queued")
        runner.submit(case.case_id)
        return {"case_id": case.case_id, "status": store.get_case(user.user_id, case.case_id).status}

    @app.put("/api/cases/{case_id}/language")
    def change_language(case_id: str, body: LanguageChange, user: UserRow = Depends(current_user)):
        """Rewrite the explanations in another language. Checks and flags do not change."""
        limiter.check(user.user_id, "confirm")
        case = own_case(case_id, user.user_id)
        if case.status != "ready":
            raise _error(409, "wrong_status", "This is available once the bill has been checked.")
        if case.language != body.language:
            result = store.get_result(case.case_id)
            store.set_language(case.case_id, body.language)
            store.record_event("language_switched", user.user_id, language=body.language)
            store.put_result(case.case_id, dict(result, confirmed=True))
            store.set_status(case.case_id, "queued")
            runner.submit(case.case_id)
        return {"case_id": case.case_id, "status": store.get_case(user.user_id, case.case_id).status}

    @app.post("/api/cases/{case_id}/letter")
    def letter(case_id: str, body: LetterRequest, request: Request, user: UserRow = Depends(current_user)):
        limiter.check(user.user_id, "letter")
        case = own_case(case_id, user.user_id)
        if case.status != "ready":
            raise _error(409, "wrong_status", "Letters are available once the bill has been checked.")
        result = store.get_result(case.case_id)
        bill = Bill.model_validate(result["bill"])
        eob = Eob.model_validate(result["eob"]) if result.get("eob") else None
        patient = Patient(**body.patient.model_dump())
        today = settings.today()
        try:
            if body.kind == "itemized_request":
                out = itemized_request(bill, patient, today, body.note)
            elif body.kind == "financial_assistance":
                out = financial_assistance(bill, patient, today, body.note)
            elif body.kind == "payment_plan":
                out = payment_plan(bill, patient, today, body.monthly_amount, body.note)
            elif body.kind == "insurer_appeal":
                if not eob or not any(sl.status in ("denied", "not_processed") for sl in eob.service_lines):
                    raise _error(422, "no_denials", "An appeal needs an EOB that shows a denied service.")
                out = insurer_appeal(bill, eob, patient, today, body.note)
            else:
                flags = [Flag.model_validate(f) for f in result["flags"]]
                if body.flag_ids is not None:
                    by_id = {f.flag_id: f for f in flags}
                    unknown = [i for i in body.flag_ids if i not in by_id]
                    if unknown:
                        raise _error(422, "unknown_flag", "Some selected flags are not part of this case.")
                    flags = [by_id[i] for i in body.flag_ids]
                if not flags:
                    raise _error(422, "no_flags", "Choose at least one item to include in the letter.")
                packet_id = new_packet_id()
                verify_url = "{}verify?id={}".format(str(request.base_url), packet_id)
                out = dispute(bill, eob, flags, patient, today, body.note, verify_url=verify_url)
                documents = [{"kind": "bill", "sha256": store.get_upload_hashes(case.bill_upload_id)}] + [
                    {"kind": "eob", "sha256": store.get_upload_hashes(u)} for u in case.eob_upload_ids
                ]
                payload = build_payload(packet_id, settings.now(), bill, eob, flags, out.text, documents)
                store.put_packet(packet_id, case.case_id, payload, sign(payload, packet_key))
                store.record_event("packet_issued", user.user_id, items=len(flags))
        except ValueError:
            raise _error(422, "invalid_letter", "The letter could not be created from these details.")
        store.record_event("letter_created", user.user_id, kind=out.kind, format=body.format)
        if body.format == "pdf":
            filename = out.kind.replace("_", "-") + ".pdf"
            return Response(
                render_pdf(out),
                media_type="application/pdf",
                headers={"Content-Disposition": 'attachment; filename="{}"'.format(filename)},
            )
        return {"kind": out.kind, "subject": out.subject, "text": out.text, "verify_url": out.verify_url}

    def ready_result(case_id: str, user_id: str):
        case = own_case(case_id, user_id)
        if case.status != "ready":
            raise _error(409, "wrong_status", "This is available once the bill has been checked.")
        return case, store.get_result(case.case_id)

    @app.post("/api/cases/{case_id}/feedback", status_code=204)
    def flag_feedback(case_id: str, body: FlagFeedback, user: UserRow = Depends(current_user)):
        limiter.check(user.user_id, "feedback")
        case, result = ready_result(case_id, user.user_id)
        flag = next((f for f in result["flags"] if f["flag_id"] == body.flag_id), None)
        if flag is None:
            raise _error(404, "not_found", "That item is not part of this case.")
        model = getattr(settings.llm, "model", None)
        store.record_flag_feedback(case.case_id, flag["flag_id"], flag["rule"], flag["confidence"], body.verdict, model)
        store.set_radar_verdict(case.case_id, flag["flag_id"], body.verdict)
        store.record_event("flag_feedback", user.user_id, verdict=body.verdict)
        return Response(status_code=204)

    @app.post("/api/cases/{case_id}/survey", status_code=204)
    def survey(case_id: str, body: Survey, user: UserRow = Depends(current_user)):
        limiter.check(user.user_id, "feedback")
        case, result = ready_result(case_id, user.user_id)
        store.record_survey(case.case_id, body.helpful, body.most_useful, len(result["flags"]), bool(result.get("eob")))
        store.record_event("survey", user.user_id)
        return Response(status_code=204)

    @app.post("/api/ask")
    def ask(body: Question, user: UserRow = Depends(current_user)):
        """Answer a billing question from the bundled guides (and the user's bill, if case_id is given).
        The question is never stored or logged."""
        limiter.check(user.user_id, "ask")
        bill = eob = None
        flags: List[Flag] = []
        if body.case_id:
            case, result = ready_result(body.case_id, user.user_id)
            bill = Bill.model_validate(result["bill"])
            eob = Eob.model_validate(result["eob"]) if result.get("eob") else None
            flags = [Flag.model_validate(f) for f in result["flags"]]
        try:
            ans = answer_question(body.question, knowledge, settings.llm, bill=bill, eob=eob, flags=flags, language=body.language)
        except ValueError:
            raise _error(422, "invalid_question", "Please ask a shorter question.")
        if ans.reason:
            log.info("ask fallback %s", ans.reason)
        store.record_event("question_asked", user.user_id, with_bill=bool(body.case_id), answered=not ans.fallback)

        def src(s):
            return {"title": s.title, "section": s.section, "source_name": s.source_name, "source_url": s.source_url}

        return {
            "answer": ans.text,
            "fallback": ans.fallback,
            "sources": [src(s) for s in ans.sources],
            "related": [src(s) for s in ans.related],
        }

    def case_data(case_id: str, user: UserRow):
        case, result = ready_result(case_id, user.user_id)
        bill = Bill.model_validate(result["bill"])
        eob = Eob.model_validate(result["eob"]) if result.get("eob") else None
        return case, bill, eob, [Flag.model_validate(f) for f in result["flags"]]

    @app.post("/api/cases/{case_id}/rehearse")
    def rehearse(case_id: str, body: Rehearsal, user: UserRow = Depends(current_user)):
        """One turn of a practice call. With no turns yet, returns the representative's greeting
        and a suggested first line. The conversation is never stored."""
        limiter.check(user.user_id, "rehearse")
        _, bill, eob, flags = case_data(case_id, user)
        if not body.turns:
            store.record_event("rehearsal_started", user.user_id, counterpart=body.counterpart)
            return {
                "reply": opening(body.counterpart, bill, eob, body.language),
                "call_ended": False,
                "fallback": False,
                "suggested_opener": suggested_opener(bill, flags, body.language),
            }
        try:
            out = rep_reply(body.turns, body.counterpart, settings.llm, bill=bill, eob=eob, flags=flags, language=body.language)
        except ValueError:
            raise _error(422, "invalid_rehearsal", "The practice call could not continue. Please start again.")
        if out.reason:
            log.info("rehearsal fallback %s", out.reason)
        return {"reply": out.text, "call_ended": out.call_ended, "fallback": out.fallback}

    @app.post("/api/cases/{case_id}/rehearse/score")
    def rehearse_score(case_id: str, body: Rehearsal, user: UserRow = Depends(current_user)):
        limiter.check(user.user_id, "rehearse")
        _, bill, eob, flags = case_data(case_id, user)
        try:
            out = score_call(body.turns, body.counterpart, settings.llm, knowledge, bill=bill, eob=eob, flags=flags, language=body.language)
        except ValueError:
            raise _error(422, "invalid_rehearsal", "Practice the call first, then ask for feedback.")
        if out.reason:
            log.info("rehearsal score fallback %s", out.reason)
        store.record_event("rehearsal_scored", user.user_id, turns=len(body.turns), scored=not out.fallback)
        return {
            "scores": out.scores,
            "strengths": out.strengths,
            "improvements": out.improvements,
            "try_saying": out.try_saying,
            "sources": out.sources,
            "fallback": out.fallback,
            "tips": out.tips,
        }

    # --- Refund finder ---------------------------------------------------------------------

    def user_episodes(user: UserRow):
        statements = []
        for case in store.list_cases(user.user_id):
            if case.status != "ready":
                continue
            result = store.get_result(case.case_id) or {}
            if not result.get("bill"):
                continue
            eob = Eob.model_validate(result["eob"]) if result.get("eob") else None
            statements.append(Statement(case.case_id, case.created_at, Bill.model_validate(result["bill"]), eob))
        payments = [
            Payment(p["payment_id"], p["case_id"], Decimal(p["amount"]), date.fromisoformat(p["paid_on"]), p.get("note", ""))
            for p in store.list_payments(user.user_id)
        ]
        episodes = find_refunds(statements, payments)
        assigned = {p.payment_id for e in episodes for p in e.payments}
        return episodes, [p for p in payments if p.payment_id not in assigned]

    @app.get("/api/refunds")
    def refunds(user: UserRow = Depends(current_user)):
        episodes, orphans = user_episodes(user)
        found = [e for e in episodes if e.findings]
        if found:
            store.record_event("refunds_found", user.user_id, visits=len(found))
        return {
            "episodes": [episode_out(e) for e in episodes],
            "total_estimate": str(sum((e.estimate for e in episodes), Decimal("0"))),
            "unassigned_payments": [
                {"payment_id": p.payment_id, "amount": str(p.amount), "paid_on": p.paid_on.isoformat(), "note": p.note}
                for p in orphans
            ],
        }

    @app.post("/api/payments", status_code=201)
    def add_payment(body: PaymentIn, user: UserRow = Depends(current_user)):
        limiter.check(user.user_id, "payments")
        own_case(body.case_id, user.user_id)
        if body.paid_on > settings.today():
            raise _error(422, "future_date", "The payment date can't be in the future.")
        payment_id = store.add_payment(
            user.user_id,
            {"case_id": body.case_id, "amount": str(body.amount), "paid_on": body.paid_on.isoformat(), "note": body.note.strip()},
        )
        store.record_event("payment_added", user.user_id)
        return {"payment_id": payment_id}

    @app.delete("/api/payments/{payment_id}", status_code=204)
    def delete_payment(payment_id: str, user: UserRow = Depends(current_user)):
        if not store.delete_payment(user.user_id, payment_id):
            raise _error(404, "not_found", "Payment not found.")
        return Response(status_code=204)

    @app.post("/api/refunds/letter")
    def refund_request(body: RefundLetter, user: UserRow = Depends(current_user)):
        limiter.check(user.user_id, "letter")
        episodes, _ = user_episodes(user)
        ep = next((e for e in episodes if e.episode_id == body.episode_id), None)
        if ep is None:
            raise _error(404, "not_found", "That visit was not found. It may have expired.")
        try:
            out = refund_letter(ep, Patient(**body.patient.model_dump()), settings.today(), body.note)
        except ValueError:
            raise _error(422, "no_refund", "We didn't find a refund to ask for on this visit.")
        store.record_event("letter_created", user.user_id, kind=out.kind, format=body.format)
        if body.format == "pdf":
            return Response(render_pdf(out), media_type="application/pdf",
                            headers={"Content-Disposition": 'attachment; filename="refund-request.pdf"'})
        return {"kind": out.kind, "subject": out.subject, "text": out.text}

    # --- Billing error radar ---------------------------------------------------------------

    @app.get("/api/radar")
    def radar_search(q: str = "", user: UserRow = Depends(current_user)):
        """Providers with patterns reported by at least K different people."""
        key = normalize_provider(q) if q.strip() else ""
        if q.strip() and key is None:
            return {"providers": [], "k": settings.radar_k}
        rows = store.radar_providers(key or "", settings.radar_k)
        return {
            "k": settings.radar_k,
            "providers": [
                {
                    "provider_name": r["provider_name"],
                    "patterns": present(store.radar_patterns(r["provider_key"], settings.radar_k), settings.radar_k),
                }
                for r in rows
            ],
        }

    # --- Public verification of dispute packets (no login) ----------------------------------

    @app.get("/api/verify/key")
    def verify_key():
        return {"algorithm": "Ed25519", "public_key": packet_public}

    @app.get("/api/verify/{packet_id}")
    def verify_packet_endpoint(packet_id: str, request: Request):
        limiter.check(client_ip(request), "verify")
        row = store.get_packet(packet_id) if len(packet_id) <= 64 else None
        if row is None:
            raise _error(404, "not_found", "This verification link is not valid or has expired.")
        payload = row["payload"]
        return {
            "payload": payload,
            "signature": row["signature"],
            "public_key": packet_public,
            "algorithm": "Ed25519",
            "signature_valid": verify_packet(payload, row["signature"], packet_public),
        }

    @app.get("/verify", include_in_schema=False)
    def verify_page():
        page = frontend / "verify.html" if frontend else None
        if page is None or not page.is_file():
            raise _error(404, "not_found", "Verification page not available.")
        return FileResponse(page, headers={"Cache-Control": "no-cache"})

    @app.delete("/api/cases/{case_id}", status_code=204)
    def delete_case(case_id: str, user: UserRow = Depends(current_user)):
        if not store.delete_case(user.user_id, case_id):
            raise _error(404, "not_found", "Case not found. It may have expired.")
        store.record_event("case_deleted", user.user_id)
        return Response(status_code=204)

    return app


def app_from_env() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    ncci, prices = os.environ.get("BILLCHECKER_NCCI_FILE"), os.environ.get("BILLCHECKER_PRICES_FILE")
    reference = Reference(
        pairs=load_pairs(Path(ncci)) if ncci else None,
        prices=load_prices(Path(prices)) if prices else None,
        prices_label=os.environ.get("BILLCHECKER_PRICES_LABEL", "Reference price"),
    )
    return create_app(
        Settings(
            database_url=database_url,
            key=load_key(os.environ.get("BILLCHECKER_KEY")),
            llm=make_llm(),
            reference=reference,
            frontend_dir=Path(os.environ.get("BILLCHECKER_FRONTEND_DIR", DEFAULT_FRONTEND_DIR)),
            # Distinct reporters before a radar pattern shows. Keep at 10+ in production (privacy).
            radar_k=int(os.environ.get("BILLCHECKER_RADAR_K", DEFAULT_K)),
            knowledge=KnowledgeBase.from_env(embedder=GeminiEmbedder() if os.environ.get("GEMINI_API_KEY") else None),
            secure_cookies=os.environ.get("BILLCHECKER_INSECURE_COOKIES") != "1",
        )
    )
