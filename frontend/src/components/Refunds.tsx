"use client";

import { useCallback, useEffect, useState } from "react";
import { useApp } from "@/lib/app";
import { ApiError, apiBlob, saveBlob } from "@/lib/api";
import { demoOnly } from "@/lib/demo";
import { money, parseAmount, shortDate } from "@/lib/format";

interface Payment {
  payment_id: string;
  amount: string;
  paid_on: string;
  note: string;
}
interface Episode {
  episode_id: string;
  provider_name: string | null;
  service_dates: string[];
  statements: { case_id: string; statement_date: string | null; amount_due: string | null; has_eob: boolean }[];
  payments: Payment[];
  owed: string | null;
  paid: string;
  latest_balance: string | null;
  findings: { kind: string; amount: string }[];
  estimate: string;
}
interface RefundData {
  episodes: Episode[];
  total_estimate: string;
  unassigned_payments: Payment[];
}

export default function Refunds(props: { hidden: boolean; onBack: () => void }) {
  const { t, call, setError } = useApp();
  const [data, setData] = useState<RefundData | null>(null);

  const load = useCallback(() => {
    call<RefundData>("GET", "/api/refunds").then(setData).catch((e: Error) => setError(e.message));
  }, [call, setError]);

  useEffect(() => {
    if (!props.hidden) load();
  }, [props.hidden, load]);

  const total = data ? Number(data.total_estimate) : 0;
  return (
    <section id="refunds-view" hidden={props.hidden}>
      <div className="card">
        <h2>{t("refunds_title")}</h2>
        <p className="muted">{t("refunds_intro")}</p>
        {data ? (
          <p id="refunds-total" className={total > 0 ? "refund-total found" : "refund-total"}>
            {total > 0 ? t("refunds_total", { amount: money(data.total_estimate) }) : data.episodes.length ? t("refunds_none") : t("refunds_empty")}
          </p>
        ) : null}
        <p className="hint">{t("refunds_private")}</p>
      </div>
      {data?.episodes.map((ep) => <EpisodeCard key={ep.episode_id} ep={ep} onChange={load} />)}
      <button id="refunds-back" type="button" onClick={props.onBack}>{t("refunds_back")}</button>
    </section>
  );
}

function EpisodeCard({ ep, onChange }: { ep: Episode; onChange: () => void }) {
  const { lang, t, call, setError } = useApp();
  const [amount, setAmount] = useState("");
  const [paidOn, setPaidOn] = useState("");
  const [note, setNote] = useState("");
  const [name, setName] = useState("");
  const [letter, setLetter] = useState<string | null>(null);
  const latestCase = ep.statements[ep.statements.length - 1].case_id;
  const dates =
    ep.service_dates.length > 1
      ? shortDate(ep.service_dates[0], lang) + " – " + shortDate(ep.service_dates[ep.service_dates.length - 1], lang)
      : shortDate(ep.service_dates[0], lang);

  const addPayment = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const value = parseAmount(amount, t("err_amount_format"));
      if (!value || !paidOn) return setError(t("err_payment"));
      await call("POST", "/api/payments", { case_id: latestCase, amount: value, paid_on: paidOn, note: note.trim() });
      setAmount("");
      setPaidOn("");
      setNote("");
      setLetter(null);
      onChange();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const remove = async (id: string) => {
    try {
      await call("DELETE", "/api/payments/" + id);
      setLetter(null);
      onChange();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const body = () => ({ episode_id: ep.episode_id, patient: { name: name.trim(), address_lines: [] } });
  const makeLetter = async () => {
    setError("");
    if (!name.trim()) return setError(t("err_name"));
    try {
      setLetter((await call<{ text: string }>("POST", "/api/refunds/letter", body())).text);
    } catch (err) {
      setError((err as Error).message);
    }
  };
  const pdf = async () => {
    try {
      saveBlob(await apiBlob("/api/refunds/letter", { ...body(), format: "pdf" }), "refund-request.pdf");
    } catch (e) {
      setError(e instanceof ApiError && e.code === "demo" ? demoOnly(lang) : t("err_pdf"));
    }
  };

  const found = ep.findings.length > 0;
  return (
    <div className={"card episode" + (found ? " found" : "")} data-episode={ep.episode_id}>
      <h3>{t("refunds_visit", { provider: ep.provider_name ?? "—", dates })}</h3>
      <p className="muted">{t("refunds_statements", { n: ep.statements.length })}</p>
      <dl className="summary">
        <div className="summary-row"><dt>{t("refunds_owed")}</dt><dd>{ep.owed !== null ? money(ep.owed) : t("refunds_unknown")}</dd></div>
        <div className="summary-row"><dt>{t("refunds_paid")}</dt><dd>{money(ep.paid)}</dd></div>
        <div className="summary-row"><dt>{t("refunds_balance")}</dt><dd>{money(ep.latest_balance)}</dd></div>
      </dl>
      {found ? (
        <div className="refund-findings">
          <p className="refund-estimate">{t("refunds_estimate", { amount: money(ep.estimate) })}</p>
          <ul>
            {ep.findings.map((f, i) => <li key={i}>{t("refunds_finding_" + f.kind, { amount: money(f.amount) })}</li>)}
          </ul>
        </div>
      ) : null}

      <h4>{t("refunds_payments")}</h4>
      {ep.payments.length ? (
        <ul className="payments">
          {ep.payments.map((p) => (
            <li key={p.payment_id}>
              {money(p.amount)} · {shortDate(p.paid_on, lang)}{p.note ? " · " + p.note : ""}{" "}
              <button type="button" className="link" onClick={() => remove(p.payment_id)}>{t("refunds_remove")}</button>
            </li>
          ))}
        </ul>
      ) : null}
      <form className="payment-form" noValidate onSubmit={addPayment}>
        <label>
          <span>{t("refunds_amount")}</span>
          <input name="amount" type="text" inputMode="decimal" placeholder="0.00" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label>
          <span>{t("refunds_date")}</span>
          <input name="paid_on" type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
        </label>
        <label className="grow">
          <span>{t("refunds_note")}</span>
          <input name="note" type="text" maxLength={100} placeholder={t("refunds_note_hint")} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <button type="submit" className="small">{t("refunds_add_button")}</button>
      </form>

      {found ? (
        <div className="refund-letter">
          <label>
            <span>{t("refunds_letter_name")}</span>
            <input name="letter_name" type="text" autoComplete="name" maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <div className="actions">
            <button type="button" className="primary" onClick={makeLetter}>{t("refunds_letter")}</button>
            {letter ? <button type="button" onClick={pdf}>PDF</button> : null}
          </div>
          {letter ? <pre className="letter refund-letter-text" lang="en">{letter}</pre> : null}
        </div>
      ) : null}
    </div>
  );
}
