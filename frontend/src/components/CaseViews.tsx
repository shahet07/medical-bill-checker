"use client";

import { useEffect, useRef, useState } from "react";
import { useApp } from "@/lib/app";
import { money, parseAmount, shortDate } from "@/lib/format";
import type { CaseData, CaseSummary } from "@/lib/types";
import { RadarSearch } from "./Radar";
import { checkPhoto } from "@/lib/photoCheck";
import { STATIC_ONLY, at } from "@/lib/base";

const DEMO_TEXT = {
  en: {
    kicker: "Demo",
    title: "Try it with a sample bill",
    body: "This demo checks a made-up bill and insurance statement (EOB). What you'll see is a real check of this sample by Clyvexa. The demo doesn't read or upload any files.",
    button: "Check the sample bill",
    bill: "Sample bill",
    eob: "Sample EOB",
    own: "To check your own bill, run the full app. Instructions are in the",
    readme: "README",
  },
  es: {
    kicker: "Demostración",
    title: "Pruébelo con una factura de muestra",
    body: "Esta demostración revisa una factura y un estado de cuenta del seguro (EOB) inventados. Lo que verá es una revisión real de esta muestra hecha por Clyvexa. La demostración no lee ni sube ningún archivo.",
    button: "Revisar la factura de muestra",
    bill: "Factura de muestra",
    eob: "EOB de muestra",
    own: "Para revisar su propia factura, use la aplicación completa. Las instrucciones están en el",
    readme: "README",
  },
};

const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const MAX_FILES = 10;
const MAX_EOBS = 5;
const ACCEPT = "application/pdf,image/jpeg,image/png,image/heic,image/heif,.heic,.heif";

interface Warning {
  page: number;
  issues: string[];
  doc: "bill" | "eob";
}

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
  // Uploads that passed but had photo quality warnings, waiting for the user's choice.
  const [pending, setPending] = useState<{ billId: string; eobIds: string[]; warnings: Warning[] } | null>(null);
  // On-device check (TensorFlow.js) of the photos currently chosen, before upload.
  const [device, setDevice] = useState<{ checking: boolean; checked: number; flagged: { name: string; issues: string[] }[] }>({
    checking: false,
    checked: 0,
    flagged: [],
  });

  const checkOnDevice = async () => {
    const inputs = Array.from(formRef.current?.querySelectorAll<HTMLInputElement>("#bill-file, .eob-file") ?? []);
    const files = inputs.flatMap((i) => Array.from(i.files ?? []));
    const photos = files.filter((f) => /^image\/(jpeg|png|webp)$/.test(f.type));
    if (!photos.length) return setDevice({ checking: false, checked: 0, flagged: [] });
    setDevice({ checking: true, checked: 0, flagged: [] });
    const flagged: { name: string; issues: string[] }[] = [];
    let checked = 0;
    for (const f of photos) {
      try {
        const r = await checkPhoto(f);
        if (!r) continue;
        checked++;
        if (r.issues.length) flagged.push({ name: f.name, issues: r.issues });
      } catch {
        /* model unavailable: the server-side check still runs at upload */
      }
    }
    setDevice({ checking: false, checked, flagged });
  };

  // A fresh form each time the upload screen is shown again.
  useEffect(() => {
    formRef.current?.reset();
    setEobSlots(1);
    setPending(null);
    setDevice({ checking: false, checked: 0, flagged: [] });
  }, [props.historyKey]);

  const createCase = async (billId: string, eobIds: string[]) => {
    const created = await call<{ case_id: string }>("POST", "/api/cases", { bill_upload_id: billId, eob_upload_ids: eobIds, language: lang });
    props.onCreated(created.case_id);
  };

  const uploadFiles = async (kind: "bill" | "eob", files: FileList) => {
    const list = Array.from(files);
    if (list.length > MAX_FILES) throw new Error(t("err_too_many_files"));
    if (list.reduce((n, f) => n + f.size, 0) > MAX_UPLOAD_BYTES) throw new Error(t("err_too_large"));
    const form = new FormData();
    form.append("kind", kind);
    for (const f of list) form.append("file", f);
    return call<{ upload_id: string; quality: { page: number; issues: string[] }[] }>("POST", "/api/uploads", form);
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
      const warnings: Warning[] = billUp.quality.filter((q) => q.issues.length).map((q) => ({ ...q, doc: "bill" }));
      const eobIds: string[] = [];
      for (const files of eobs) {
        const up = await uploadFiles("eob", files);
        eobIds.push(up.upload_id);
        warnings.push(...up.quality.filter((q) => q.issues.length).map((q) => ({ ...q, doc: "eob" as const })));
      }
      // If the on-device check already warned about these photos, don't ask twice.
      if (warnings.length && device.flagged.length === 0) {
        setPending({ billId: billUp.upload_id, eobIds, warnings });
        return;
      }
      await createCase(billUp.upload_id, eobIds);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // Demo build: check the recorded sample (no files are read).
  const runSample = async () => {
    setError("");
    setBusy(true);
    try {
      const sample = (kind: string) => {
        const form = new FormData();
        form.append("kind", kind);
        return call<{ upload_id: string }>("POST", "/api/uploads", form);
      };
      const bill = await sample("bill");
      const eob = await sample("eob");
      await createCase(bill.upload_id, [eob.upload_id]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const demo = DEMO_TEXT[lang];

  return (
    <section id="upload-view" className="card" hidden={props.hidden}>
      {STATIC_ONLY ? (
        <div className="demo-panel">
          <p className="kicker">{demo.kicker}</p>
          <h2>{demo.title}</h2>
          <p className="demo-body">{demo.body}</p>
          <div className="demo-docs">
            <figure>
              <img src={at("/demo/sample-bill.jpg")} alt={demo.bill} width={832} height={556} />
              <figcaption>{demo.bill}</figcaption>
            </figure>
            <figure>
              <img src={at("/demo/sample-eob.jpg")} alt={demo.eob} width={900} height={400} />
              <figcaption>{demo.eob}</figcaption>
            </figure>
          </div>
          <button id="demo-run" type="button" className="primary big" disabled={busy} onClick={runSample}>
            {demo.button} <span aria-hidden="true">→</span>
          </button>
          <p className="hint">
            {demo.own}{" "}
            <a href="https://github.com/shahet07/medical-bill-checker#readme" rel="noopener">
              {demo.readme}
            </a>
            .
          </p>
        </div>
      ) : (
        <h2>{ts("upload_title")}</h2>
      )}
      <form id="upload-form" hidden={STATIC_ONLY} noValidate ref={formRef} onSubmit={submit} onChange={(e) => {
        if ((e.target as HTMLElement).matches?.('input[type="file"]')) checkOnDevice();
      }}>
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
        <div id="device-check" aria-live="polite">
          {device.checking ? <p className="hint">{t("device_checking")}</p> : null}
          {!device.checking && device.flagged.length ? (
            <div className="note quality">
              <strong>{t("device_warn_title")}</strong>
              <ul>
                {device.flagged.map((f) => (
                  <li key={f.name}>{t("device_file", { name: f.name, issues: f.issues.map((i) => t("quality_" + i)).join(", ") })}</li>
                ))}
              </ul>
              <p className="hint">{t("device_note")} {t("quality_tips")}</p>
            </div>
          ) : null}
          {!device.checking && device.checked > 0 && !device.flagged.length ? <p className="hint device-ok">{t("device_ok")}</p> : null}
        </div>
        <button id="upload-button" type="submit" className="primary" disabled={busy}>
          {busy ? t("uploading") : ts("check_button")}
        </button>
      </form>
      {pending ? (
        <div id="quality-warning" className="note quality" role="alert">
          <strong>{t("quality_title")}</strong>
          <p>{t("quality_intro")}</p>
          <ul>
            {pending.warnings.map((w, i) => (
              <li key={i}>
                {t("quality_page", { doc: t(w.doc === "eob" ? "quality_doc_eob" : "quality_doc_bill"), n: w.page })}:{" "}
                {w.issues.map((issue) => t("quality_" + issue)).join(", ")}
              </li>
            ))}
          </ul>
          <p className="hint">{t("quality_tips")}</p>
          <div className="actions">
            <button id="quality-retake" type="button" onClick={() => { setPending(null); formRef.current?.reset(); }}>
              {t("quality_retake")}
            </button>
            <button id="quality-continue" type="button" className="primary" disabled={busy}
              onClick={async () => {
                const p = pending;
                setPending(null);
                setBusy(true);
                try { await createCase(p.billId, p.eobIds); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
              }}>
              {t("quality_continue")}
            </button>
          </div>
        </div>
      ) : null}
      <p className="privacy" hidden={STATIC_ONLY}>{ts("privacy")}</p>
      {props.loggedIn && !props.hidden ? <History refreshKey={props.historyKey} onOpenCase={props.onOpenCase} /> : null}
      {props.loggedIn && !props.hidden ? <RadarSearch /> : null}
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

// Shown while checking; the ticks are paced by CSS, the real status is the text below.
const STATUS_STEPS = {
  en: ["Reading the bill", "Reading your EOB", "Comparing line by line", "Writing it in plain words"],
  es: ["Leyendo la factura", "Leyendo su EOB", "Comparando línea por línea", "Explicándolo en palabras sencillas"],
};

export function StatusView(props: { hidden: boolean; caseData: CaseData | null; onCancel: () => void }) {
  const { lang, t, ts } = useApp();
  const c = props.caseData;
  const text =
    c && c.status === "queued" && c.error_code === "llm_unavailable"
      ? t("status_busy")
      : c && c.status === "queued"
        ? t("status_waiting")
        : t("status_reading");
  return (
    <section id="status-view" className="card status-card" hidden={props.hidden}>
      <h2>{ts("checking_title")}</h2>
      <div className="scanner" aria-hidden="true">
        <div className="scan-doc">
          <i />
          <i />
          <i className="hit" />
          <i />
          <i className="hit" />
          <i className="short" />
        </div>
        <div className="scan-glass">
          <svg viewBox="0 0 40 40">
            <path d="M28 12.5A10.5 10.5 0 1 0 28 27.5" />
            <path d="M27.5 29l5 5" />
          </svg>
        </div>
        <ol className="scan-steps">
          {STATUS_STEPS[lang].map((step, i) => (
            <li key={step} className={"s" + i}>
              <span className="tick" />
              {step}
            </li>
          ))}
        </ol>
      </div>
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
