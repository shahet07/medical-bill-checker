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
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Deque, Dict, List, Literal, Optional, Tuple

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

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
from .reference import Reference, load_pairs, load_prices
from .store import Store, hash_session, load_key, pack_files

log = logging.getLogger("billchecker.api")

WEB_DIR = Path(__file__).parent / "web"
# Same-origin only, no inline script or style, no framing, no third-party anything.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; form-action 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'"
)
SESSION_COOKIE = "bc_session"
MIME = {"pdf": "application/pdf", "png": "image/png", "jpeg": "image/jpeg", "heic": "image/heic"}
MAX_EOBS = 5
# action -> (max requests, window in seconds), per session
DEFAULT_LIMITS = {"upload": (20, 3600), "case": (10, 3600), "letter": (60, 3600), "confirm": (20, 3600), "feedback": (100, 3600)}


@dataclass
class Settings:
    data_dir: Path
    key: bytes
    llm: JsonLLM
    reference: Reference = field(default_factory=Reference)
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
    runner = CaseRunner(store, settings.llm, inline=settings.inline_jobs, reference=settings.reference)
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
    def upload(kind: Literal["bill", "eob"] = Form(...), file: List[UploadFile] = File(...), sess: str = Depends(session)):
        """One document, as one file or several (e.g. a photo of each page)."""
        limiter.check(sess, "upload")
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
        row = store.add_upload(sess, kind, mime, len(doc.pages), pack_files(files))
        return {"upload_id": row.upload_id, "kind": kind, "page_count": row.page_count, "expires_at": row.expires_at}

    @app.post("/api/cases", status_code=201)
    def create_case(body: CreateCase, sess: str = Depends(session)):
        limiter.check(sess, "case")
        bill = store.get_upload(sess, body.bill_upload_id) if len(body.bill_upload_id) == 32 else None
        if bill is None or bill.kind != "bill":
            raise _error(404, "not_found", "Bill upload not found. It may have expired.")
        eob_ids = list(dict.fromkeys(body.eob_upload_ids + ([body.eob_upload_id] if body.eob_upload_id else [])))
        if len(eob_ids) > MAX_EOBS:
            raise _error(422, "too_many_eobs", "Please add at most 5 EOBs to one bill.")
        for eob_id in eob_ids:
            eob = store.get_upload(sess, eob_id) if len(eob_id) == 32 else None
            if eob is None or eob.kind != "eob":
                raise _error(404, "not_found", "EOB upload not found. It may have expired.")
        case = store.add_case(sess, body.bill_upload_id, eob_ids, body.language)
        runner.submit(case.case_id)
        case = store.get_case(sess, case.case_id)
        return {"case_id": case.case_id, "status": case.status}

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str, sess: str = Depends(session)):
        case = own_case(case_id, sess)
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

    @app.put("/api/cases/{case_id}/bill")
    def edit_bill(case_id: str, body: BillEdit, sess: str = Depends(session)):
        limiter.check(sess, "confirm")
        case = own_case(case_id, sess)
        if case.status not in ("ready", "needs_confirmation"):
            raise _error(409, "wrong_status", "The bill can be edited once it has been read.")
        result = store.get_result(case.case_id)
        try:
            bill = apply_edit(Bill.model_validate(result["bill"]), body)
        except ValueError:
            raise _error(422, "invalid_edit", "Some of the corrected values are not valid.")
        result = dict(result, bill=bill.model_dump(mode="json"), confirmed=True, user_edited=True, problems=[])
        store.put_result(case.case_id, dict(result, flags=[], explanations=None))
        store.set_status(case.case_id, "queued")
        runner.submit(case.case_id)
        return {"case_id": case.case_id, "status": store.get_case(sess, case.case_id).status}

    @app.put("/api/cases/{case_id}/language")
    def change_language(case_id: str, body: LanguageChange, sess: str = Depends(session)):
        """Rewrite the explanations in another language. Checks and flags do not change."""
        limiter.check(sess, "confirm")
        case = own_case(case_id, sess)
        if case.status != "ready":
            raise _error(409, "wrong_status", "This is available once the bill has been checked.")
        if case.language != body.language:
            result = store.get_result(case.case_id)
            store.set_language(case.case_id, body.language)
            store.put_result(case.case_id, dict(result, confirmed=True))
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
                out = dispute(bill, eob, flags, patient, today, body.note)
        except ValueError:
            raise _error(422, "invalid_letter", "The letter could not be created from these details.")
        if body.format == "pdf":
            filename = out.kind.replace("_", "-") + ".pdf"
            return Response(
                render_pdf(out),
                media_type="application/pdf",
                headers={"Content-Disposition": 'attachment; filename="{}"'.format(filename)},
            )
        return {"kind": out.kind, "subject": out.subject, "text": out.text}

    def ready_result(case_id: str, sess: str):
        case = own_case(case_id, sess)
        if case.status != "ready":
            raise _error(409, "wrong_status", "This is available once the bill has been checked.")
        return case, store.get_result(case.case_id)

    @app.post("/api/cases/{case_id}/feedback", status_code=204)
    def flag_feedback(case_id: str, body: FlagFeedback, sess: str = Depends(session)):
        limiter.check(sess, "feedback")
        case, result = ready_result(case_id, sess)
        flag = next((f for f in result["flags"] if f["flag_id"] == body.flag_id), None)
        if flag is None:
            raise _error(404, "not_found", "That item is not part of this case.")
        model = getattr(settings.llm, "model", None)
        store.record_flag_feedback(case.case_id, flag["flag_id"], flag["rule"], flag["confidence"], body.verdict, model)
        return Response(status_code=204)

    @app.post("/api/cases/{case_id}/survey", status_code=204)
    def survey(case_id: str, body: Survey, sess: str = Depends(session)):
        limiter.check(sess, "feedback")
        case, result = ready_result(case_id, sess)
        store.record_survey(case.case_id, body.helpful, body.most_useful, len(result["flags"]), bool(result.get("eob")))
        return Response(status_code=204)

    @app.delete("/api/cases/{case_id}", status_code=204)
    def delete_case(case_id: str, sess: str = Depends(session)):
        if not (len(case_id) == 32 and store.delete_case(sess, case_id)):
            raise _error(404, "not_found", "Case not found. It may have expired.")
        return Response(status_code=204)

    return app


def app_from_env() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    data_dir = Path(os.environ.get("BILLCHECKER_DATA_DIR", Path.home() / ".billchecker" / "data"))
    ncci, prices = os.environ.get("BILLCHECKER_NCCI_FILE"), os.environ.get("BILLCHECKER_PRICES_FILE")
    reference = Reference(
        pairs=load_pairs(Path(ncci)) if ncci else None,
        prices=load_prices(Path(prices)) if prices else None,
        prices_label=os.environ.get("BILLCHECKER_PRICES_LABEL", "Reference price"),
    )
    return create_app(
        Settings(
            data_dir=data_dir,
            key=load_key(os.environ.get("BILLCHECKER_KEY")),
            llm=make_llm(),
            reference=reference,
            secure_cookies=os.environ.get("BILLCHECKER_INSECURE_COOKIES") != "1",
        )
    )
