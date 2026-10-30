"""HTTP API.

No accounts in v1: an anonymous session cookie (HttpOnly, Secure,
SameSite=Strict) scopes everything. Another session's IDs return 404, the
same as IDs that do not exist. Patient details for letters are used once to
render the letter and are never stored.

Run locally:
    export BILLCHECKER_KEY=$(python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())")
    export GEMINI_API_KEY=...
    .venv/bin/uvicorn --factory billchecker.api:app_from_env
"""

import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Deque, Dict, List, Literal, Optional, Tuple

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .ingest import MAX_BYTES, IngestError, ingest, sniff_type
from .letters import MAX_NOTE_CHARS, Patient, dispute, itemized_request
from .llm import JsonLLM, make_llm
from .models import Bill, Eob, Flag, Money
from .pipeline import CaseRunner
from .store import Store, hash_session, load_key

log = logging.getLogger("billchecker.api")

WEB_DIR = Path(__file__).parent / "web"
# Same-origin only, no inline script or style, no framing, no third-party anything.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; form-action 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'"
)
SESSION_COOKIE = "bc_session"
MIME = {"pdf": "application/pdf", "png": "image/png", "jpeg": "image/jpeg"}
# action -> (max requests, window in seconds), per session
DEFAULT_LIMITS = {"upload": (20, 3600), "case": (10, 3600), "letter": (60, 3600), "confirm": (20, 3600)}


@dataclass
class Settings:
    data_dir: Path
    key: bytes
    llm: JsonLLM
    secure_cookies: bool = True
    inline_jobs: bool = False
    cleanup_interval: Optional[float] = 3600.0  # seconds; None disables the background sweep
    limits: Dict[str, Tuple[int, int]] = field(default_factory=lambda: dict(DEFAULT_LIMITS))
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    today: Callable[[], date] = lambda: date.today()


# --- Request bodies -------------------------------------------------------------------


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateCase(_Body):
    bill_upload_id: str
    eob_upload_id: Optional[str] = None


class ConfirmTotals(_Body):
    billed: Optional[Money] = None
    patient_balance: Optional[Money] = None


class PatientIn(_Body):
    name: str = Field(min_length=1, max_length=200)
    address_lines: List[str] = Field(default_factory=list, max_length=4)
    phone: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=200)
    account_number: Optional[str] = Field(default=None, max_length=50)


class LetterRequest(_Body):
    kind: Literal["itemized_request", "dispute"]
    patient: PatientIn
    flag_ids: Optional[List[str]] = None  # dispute only; default all flags
    note: Optional[str] = Field(default=None, max_length=MAX_NOTE_CHARS)


# --- Helpers ----------------------------------------------------------------------------


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": code, "message": message})


class RateLimiter:
    def __init__(self, limits: Dict[str, Tuple[int, int]]):
        self.limits = limits
        self._hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, session_hash: str, action: str) -> None:
        count, window = self.limits[action]
        now = time.monotonic()
        with self._lock:
            hits = self._hits[(session_hash, action)]
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= count:
                raise _error(429, "rate_limited", "Too many requests. Please wait a while and try again.")
            hits.append(now)


# --- App ------------------------------------------------------------------------------


def create_app(settings: Settings) -> FastAPI:
    store = Store(settings.data_dir, settings.key, now=settings.now)
    runner = CaseRunner(store, settings.llm, inline=settings.inline_jobs)
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

    app = FastAPI(title="Medical Bill Checker", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.runner = runner

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers["Content-Security-Policy"] = CSP
        return response

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    def session(request: Request, response: Response) -> str:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            token = secrets.token_urlsafe(32)
            response.set_cookie(
                SESSION_COOKIE,
                token,
                max_age=int(store.ttl.total_seconds()),
                httponly=True,
                secure=settings.secure_cookies,
                samesite="strict",
            )
        return hash_session(token)

    def own_case(case_id: str, sess: str):
        case = store.get_case(sess, case_id) if len(case_id) == 32 else None
        if case is None:
            raise _error(404, "not_found", "Case not found. It may have expired.")
        return case

    @app.post("/api/uploads", status_code=201)
    def upload(kind: Literal["bill", "eob"] = Form(...), file: UploadFile = File(...), sess: str = Depends(session)):
        limiter.check(sess, "upload")
        data = file.file.read(MAX_BYTES + 1)
        try:
            doc = ingest(data)  # validates type, size, pages, readability up front
        except IngestError as exc:
            raise _error(422, exc.code, exc.message)
        row = store.add_upload(sess, kind, MIME[sniff_type(data)], len(doc.pages), data)
        return {"upload_id": row.upload_id, "kind": kind, "page_count": row.page_count, "expires_at": row.expires_at}

    @app.post("/api/cases", status_code=201)
    def create_case(body: CreateCase, sess: str = Depends(session)):
        limiter.check(sess, "case")
        bill = store.get_upload(sess, body.bill_upload_id) if len(body.bill_upload_id) == 32 else None
        if bill is None or bill.kind != "bill":
            raise _error(404, "not_found", "Bill upload not found. It may have expired.")
        if body.eob_upload_id:
            eob = store.get_upload(sess, body.eob_upload_id) if len(body.eob_upload_id) == 32 else None
            if eob is None or eob.kind != "eob":
                raise _error(404, "not_found", "EOB upload not found. It may have expired.")
        case = store.add_case(sess, body.bill_upload_id, body.eob_upload_id)
        runner.submit(case.case_id)
        case = store.get_case(sess, case.case_id)
        return {"case_id": case.case_id, "status": case.status}

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str, sess: str = Depends(session)):
        case = own_case(case_id, sess)
        out = {"case_id": case.case_id, "status": case.status, "error_code": case.error_code, "expires_at": case.expires_at}
        result = store.get_result(case.case_id) if case.status in ("ready", "needs_confirmation", "failed") else None
        if result:
            out.update(
                {k: result[k] for k in ("bill", "eob", "eob_status", "flags", "explanations", "problems", "warnings")}
            )
            out["error_message"] = result.get("error_message")
        return out

    @app.post("/api/cases/{case_id}/confirm")
    def confirm(case_id: str, body: ConfirmTotals, sess: str = Depends(session)):
        limiter.check(sess, "confirm")
        case = own_case(case_id, sess)
        if case.status != "needs_confirmation":
            raise _error(409, "wrong_status", "This case does not need confirmation.")
        result = store.get_result(case.case_id)
        bill = Bill.model_validate(result["bill"])
        totals = bill.totals.model_copy(update={"billed": body.billed, "patient_balance": body.patient_balance})
        bill = bill.model_copy(update={"totals": totals})
        store.put_result(case.case_id, dict(result, bill=bill.model_dump(mode="json"), confirmed=True, problems=[]))
        store.set_status(case.case_id, "queued")
        runner.submit(case.case_id)
        return {"case_id": case.case_id, "status": store.get_case(sess, case.case_id).status}

    @app.post("/api/cases/{case_id}/letter")
    def letter(case_id: str, body: LetterRequest, sess: str = Depends(session)):
        limiter.check(sess, "letter")
        case = own_case(case_id, sess)
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
                out = dispute(bill, eob, flags, patient, today, body.note)
        except ValueError:
            raise _error(422, "invalid_letter", "The letter could not be created from these details.")
        return {"kind": out.kind, "subject": out.subject, "text": out.text}

    @app.delete("/api/cases/{case_id}", status_code=204)
    def delete_case(case_id: str, sess: str = Depends(session)):
        if not (len(case_id) == 32 and store.delete_case(sess, case_id)):
            raise _error(404, "not_found", "Case not found. It may have expired.")
        return Response(status_code=204)

    return app


def app_from_env() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    data_dir = Path(os.environ.get("BILLCHECKER_DATA_DIR", Path.home() / ".billchecker" / "data"))
    return create_app(
        Settings(
            data_dir=data_dir,
            key=load_key(os.environ.get("BILLCHECKER_KEY")),
            llm=make_llm(),
            secure_cookies=os.environ.get("BILLCHECKER_INSECURE_COOKIES") != "1",
        )
    )
