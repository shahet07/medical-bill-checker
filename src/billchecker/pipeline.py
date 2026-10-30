"""Runs a case through ingest -> extraction -> rules -> explanations.

Case status flow:
    queued -> extracting -> ready
                         -> needs_confirmation -> (user confirms) -> queued -> ready
                         -> failed
    LLM outage: back to queued and retried later, up to MAX_ATTEMPTS.

Logs carry case IDs, statuses, and exception type names only, never
document text or amounts.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

from .explanation import explain
from .extraction import extract_bill, extract_eob, merge_eobs
from .ingest import IngestError, ingest_many
from .llm import JsonLLM, LLMUnavailable
from .models import Bill, Eob
from .rules import run_rules
from .store import CaseRow, Store, unpack_files

log = logging.getLogger("billchecker.pipeline")

MAX_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 60.0

UNREADABLE_BILL = "We could not read this bill. Please upload a clearer photo or the PDF version."


class CaseRunner:
    def __init__(
        self,
        store: Store,
        llm: JsonLLM,
        inline: bool = False,
        workers: int = 2,
        retry_delay: float = RETRY_DELAY_SECONDS,
    ):
        self.store = store
        self.llm = llm
        self.inline = inline  # run jobs synchronously (tests, scripts)
        self.retry_delay = retry_delay
        self._executor = None if inline else ThreadPoolExecutor(max_workers=workers, thread_name_prefix="case")

    def submit(self, case_id: str) -> None:
        if self._executor is None:
            self.run(case_id)
        else:
            self._executor.submit(self.run, case_id)

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False)

    def run(self, case_id: str) -> None:
        case = self.store.get_case(None, case_id)
        if case is None or case.status not in ("queued",):
            return
        self._set(case_id, "extracting", bump=True)
        try:
            self._process(case)
        except LLMUnavailable:
            if case.attempts + 1 >= MAX_ATTEMPTS:
                self._set(case_id, "failed", "llm_unavailable")
            else:
                self._set(case_id, "queued", "llm_unavailable")
                self._schedule_retry(case_id)
        except IngestError as exc:
            self.store.put_result(case_id, _result(error_message=exc.message))
            self._set(case_id, "failed", exc.code)
        except Exception as exc:  # never log the message: it may quote document data
            log.error("case %s failed with %s", case_id, type(exc).__name__)
            self._set(case_id, "failed", "internal_error")

    def _process(self, case: CaseRow) -> None:
        previous = self.store.get_result(case.case_id)
        if previous and previous.get("confirmed"):
            # User confirmed totals; extraction is done, only finish the analysis.
            bill = Bill.model_validate(previous["bill"])
            eob = Eob.model_validate(previous["eob"]) if previous.get("eob") else None
            return self._finish(case, bill, eob, previous)

        bill_res = extract_bill(ingest_many(self._files(case.bill_upload_id)), self.llm)
        if bill_res.data is None:
            self.store.put_result(case.case_id, _result(error_message=UNREADABLE_BILL, problems=bill_res.problems))
            return self._set(case.case_id, "failed", "unreadable")

        eob, eob_status, warnings = None, "none", list(bill_res.warnings)
        if case.eob_upload_ids:
            read = []
            for n, upload_id in enumerate(case.eob_upload_ids, 1):
                doc = ingest_many(self._files(upload_id))
                eob_res = extract_eob(doc, self.llm)
                if eob_res.data is not None:
                    read.append((eob_res.data, len(doc.pages)))
                warnings += ["EOB {}: {}".format(n, w) for w in eob_res.warnings]
            eob = merge_eobs(read) if read else None
            eob_status = "ok" if len(read) == len(case.eob_upload_ids) else "partial" if read else "unreadable"

        result = _result(
            bill=bill_res.data.model_dump(mode="json"),
            eob=eob.model_dump(mode="json") if eob else None,
            eob_status=eob_status,
            problems=bill_res.problems,
            warnings=warnings,
        )
        if bill_res.status == "needs_confirmation":
            self.store.put_result(case.case_id, result)
            return self._set(case.case_id, "needs_confirmation")
        self._finish(case, bill_res.data, eob, result)

    def _finish(self, case: CaseRow, bill: Bill, eob: Optional[Eob], result: Dict[str, Any]) -> None:
        case_id = case.case_id
        flags = run_rules(bill, eob, eob_complete=result.get("eob_status") != "partial")
        expl = explain(bill, flags, self.llm, language=case.language)
        for p in expl.problems:
            log.info("case %s explanation fallback %s", case_id, p)
        result = dict(
            result,
            flags=[f.model_dump(mode="json") for f in flags],
            explanations={
                "lines": {k: {"text": v.text, "source": v.source} for k, v in expl.lines.items()},
                "flags": {k: {"text": v.text, "source": v.source} for k, v in expl.flags.items()},
            },
        )
        self.store.put_result(case_id, result)
        self._set(case_id, "ready")

    def _files(self, upload_id: str):
        data = self.store.get_blob(upload_id)
        if data is None:
            raise IngestError("expired", "This upload has expired. Please upload the file again.")
        return unpack_files(data)

    def _set(self, case_id: str, status: str, error_code: Optional[str] = None, bump: bool = False) -> None:
        self.store.set_status(case_id, status, error_code, bump_attempts=bump)
        log.info("case %s status=%s%s", case_id, status, " error=" + error_code if error_code else "")

    def _schedule_retry(self, case_id: str) -> None:
        if self.inline:
            return  # tests drive retries explicitly
        timer = threading.Timer(self.retry_delay, self.submit, args=(case_id,))
        timer.daemon = True
        timer.start()


def _result(**fields: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "bill": None,
        "eob": None,
        "eob_status": "none",
        "problems": [],
        "warnings": [],
        "confirmed": False,
        "flags": [],
        "explanations": None,
        "error_message": None,
    }
    base.update(fields)
    return base
