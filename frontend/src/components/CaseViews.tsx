"use client";

import { useEffect, useRef, useState } from "react";
import { useApp } from "@/lib/app";
import { money, parseAmount, shortDate } from "@/lib/format";
import type { CaseData, CaseSummary } from "@/lib/types";

const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const MAX_FILES = 10;
const MAX_EOBS = 5;
const ACCEPT = "application/pdf,image/jpeg,image/png,image/heic,image/heif,.heic,.heif";

// --- Upload and history ----------------------------------------------------------------------

export function UploadView(props: {
  hidden: boolean;
  historyKey: number;
  loggedIn: boolean;
  onCreated: (caseId: string) => void;
  onOpenCase: (caseId: string) => void;
}) {
  const { lang, t, ts, call, setError } = useApp();
  const [eobSlots, setEobSlots] = useState(1);
  const [busy, setBusy] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);

  // A fresh form each time the upload screen is shown again.
  useEffect(() => {
    formRef.current?.reset();
    setEobSlots(1);
  }, [props.historyKey]);

  const uploadFiles = async (kind: "bill" | "eob", files: FileList) => {
    const list = Array.from(files);
    if (list.length > MAX_FILES) throw new Error(t("err_too_many_files"));
    if (list.reduce((n, f) => n + f.size, 0) > MAX_UPLOAD_BYTES) throw new Error(t("err_too_large"));
    const form = new FormData();
    form.append("kind", kind);
    for (const f of list) form.append("file", f);
    return call<{ upload_id: string }>("POST", "/api/uploads", form);
  };

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError("");
    const form = e.currentTarget;
    const bill = (form.querySelector("#bill-file") as HTMLInputElement).files;
    const eobs = Array.from(form.querySelectorAll<HTMLInputElement>(".eob-file"))
      .map((i) => i.files)
      .filter((f): f is FileList => !!f && f.length > 0);
    if (!bill || !bill.length) return setError(t("err_choose_bill"));
    setBusy(true);
    try {
      const billUp = await uploadFiles("bill", bill);
      const eobIds: string[] = [];
      for (const files of eobs) eobIds.push((await uploadFiles("eob", files)).upload_id);
      const created = await call<{ case_id: string }>("POST", "/api/cases", {
        bill_upload_id: billUp.upload_id,
        eob_upload_ids: eobIds,
        language: lang,
      });
      props.onCreated(created.case_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section id="upload-view" className="card" hidden={props.hidden}>
      <h2>{ts("upload_title")}</h2>
      <form id="upload-form" noValidate ref={formRef} onSubmit={submit}>
        <div className="field">
          <label htmlFor="bill-file">
            <span>{ts("bill_label")}</span> <span className="req">{ts("required")}</span>
          </label>
          <input id="bill-file" name="bill" type="file" accept={ACCEPT} multiple required />
          <p className="hint">{ts("bill_hint")}</p>
        </div>
        <div className="field">
          <label htmlFor="eob-file">
            <span>{ts("eob_label")}</span> <span className="opt">{ts("optional")}</span>
          </label>
          <div id="eob-inputs">
            {Array.from({ length: eobSlots }, (_, i) => (
              <input
                key={i}
                id={i === 0 ? "eob-file" : undefined}
                className="eob-file"
                name="eob"
                type="file"
                accept={ACCEPT}
                multiple
                aria-label={i === 0 ? undefined : t("eob_n", { n: i + 1 })}
              />
            ))}
          </div>
          <button id="add-eob" type="button" className="link" hidden={eobSlots >= MAX_EOBS} onClick={() => setEobSlots((n) => Math.min(n + 1, MAX_EOBS))}>
            {ts("add_eob")}
          </button>
          <p className="hint">{ts("eob_hint")}</p>
        </div>
        <button id="upload-button" type="submit" className="primary" disabled={busy}>
          {busy ? t("uploading") : ts("check_button")}
        </button>
      </form>
      <p className="privacy">{ts("privacy")}</p>
      {props.loggedIn && !props.hidden ? <History refreshKey={props.historyKey} onOpenCase={props.onOpenCase} /> : null}
    </section>
  );
}

function History(props: { refreshKey: number; onOpenCase: (id: string) => void }) {
  const { lang, t, ts, call } = useApp();
  const [cases, setCases] = useState<CaseSummary[]>([]);

  useEffect(() => {
    call<{ cases: CaseSummary[] }>("GET", "/api/cases")
      .then((d) => setCases(d.cases))
      .catch(() => setCases([]));
  }, [props.refreshKey, call]);

  return (
    <div id="history" hidden={cases.length === 0}>
      <h2>{ts("history_title")}</h2>
      <ul id="history-list" className="history">
        {cases.map((c) => {
          const detail =
            c.status === "ready"
              ? [c.amount_due ? t("history_due", { amount: money(c.amount_due) }) : null, c.flag_count ? t("history_flags", { n: c.flag_count }) : t("history_none")]
              : [t("status_short_" + c.status)];
          return (
            <li key={c.case_id}>
              <button type="button" className="history-item" onClick={() => props.onOpenCase(c.case_id)}>
                <span className="history-main">{c.provider_name || t("history_bill")}</span>
                <span className="history-meta">{[shortDate(c.created_at, lang), ...detail.filter(Boolean)].join(" · ")}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// --- Working, confirming, failed ----------------------------------------------------------

export function StatusView(props: { hidden: boolean; caseData: CaseData | null; onCancel: () => void }) {
  const { t, ts } = useApp();
  const c = props.caseData;
  const text =
    c && c.status === "queued" && c.error_code === "llm_unavailable"
      ? t("status_busy")
      : c && c.status === "queued"
        ? t("status_waiting")
        : t("status_reading");
  return (
    <section id="status-view" className="card" hidden={props.hidden}>
      <h2>{ts("checking_title")}</h2>
      <div className="status-row">
        <span className="spinner" aria-hidden="true" />
        <p id="status-text" aria-live="polite">{text}</p>
      </div>
      <button id="cancel-button" type="button" className="link" onClick={props.onCancel}>
        {ts("cancel_delete")}
      </button>
    </section>
  );
}

export function ConfirmView(props: {
  hidden: boolean;
  caseData: CaseData | null;
  caseId: string | null;
  onSubmitted: (id: string) => void;
}) {
  const { t, ts, call, setError } = useApp();
  const [billed, setBilled] = useState("");
  const [balance, setBalance] = useState("");
  const totals = props.caseData?.bill?.totals;

  useEffect(() => {
    setBilled(totals?.billed ?? "");
    setBalance(totals?.patient_balance ?? "");
  }, [totals?.billed, totals?.patient_balance]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!props.caseId) return;
    try {
      const body = { billed: parseAmount(billed, t("err_amount_format")), patient_balance: parseAmount(balance, t("err_amount_format")) };
      await call("POST", "/api/cases/" + props.caseId + "/confirm", body);
      props.onSubmitted(props.caseId);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <section id="confirm-view" className="card" hidden={props.hidden}>
      <h2>{ts("confirm_title")}</h2>
      <p>{ts("confirm_intro")}</p>
      <ul id="confirm-problems" className="problems">
        {(props.caseData?.problems ?? []).map((p, i) => (
          <li key={i}>{p}</li>
        ))}
      </ul>
      <form id="confirm-form" noValidate onSubmit={submit}>
        <div className="field">
          <label htmlFor="confirm-billed">{ts("total_charges")}</label>
          <input id="confirm-billed" type="text" inputMode="decimal" placeholder={ts("eg_1250")} autoComplete="off" value={billed} onChange={(e) => setBilled(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="confirm-balance">{ts("amount_due_long")}</label>
          <input id="confirm-balance" type="text" inputMode="decimal" placeholder={ts("eg_350")} autoComplete="off" value={balance} onChange={(e) => setBalance(e.target.value)} />
        </div>
        <p className="hint">{ts("leave_empty")}</p>
        <button type="submit" className="primary">{ts("confirm_button")}</button>
      </form>
    </section>
  );
}

export function FailedView(props: { hidden: boolean; caseData: CaseData | null; onRestart: () => void }) {
  const { lang, t, ts } = useApp();
  const c = props.caseData;
  const known = ["unreadable", "llm_unavailable", "expired", "internal_error"];
  const fromCode = c?.error_code && known.includes(c.error_code) ? t("failed_" + c.error_code) : t("failed_internal_error");
  const text = lang === "en" && c?.error_message ? c.error_message : fromCode;
  return (
    <section id="failed-view" className="card" hidden={props.hidden}>
      <h2>{ts("failed_title")}</h2>
      <p id="failed-text">{text}</p>
      <button id="failed-restart" type="button" className="primary" onClick={props.onRestart}>
        {ts("try_again")}
      </button>
    </section>
  );
}
