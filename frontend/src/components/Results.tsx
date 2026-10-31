"use client";

import { useEffect, useState } from "react";
import { useApp } from "@/lib/app";
import { ApiError, apiBlob, saveBlob } from "@/lib/api";
import { demoOnly } from "@/lib/demo";
import { money, parseAmount, shortDate } from "@/lib/format";
import { GLOSSARY } from "@/lib/i18n";
import type { AskResult, CaseData, Flag, Letter, LineItem, Source } from "@/lib/types";
import { RadarCard } from "./Radar";
import Rehearse from "./Rehearse";

interface Props {
  hidden: boolean;
  caseId: string | null;
  caseData: CaseData | null;
  onResubmitted: (caseId: string) => void;
  onNewBill: () => void;
  onDelete: () => void;
}

export default function Results(props: Props) {
  const c = props.caseData;
  const [included, setIncluded] = useState<Set<string>>(new Set());
  // Every flag starts ticked for the letter whenever a new set of flags arrives.
  const flagKey = (c?.flags ?? []).map((f) => f.flag_id).join("|");
  useEffect(() => setIncluded(new Set((c?.flags ?? []).map((f) => f.flag_id))), [flagKey, c?.case_id]);

  return (
    <section id="results-view" hidden={props.hidden}>
      {c && c.bill && props.caseId ? (
        <>
          <Summary c={c} />
          <Flags c={c} caseId={props.caseId} included={included} setIncluded={setIncluded} />
          <RadarCard provider={c.bill.provider_name ?? ""} patterns={c.radar ?? []} />
          <Ask caseId={props.caseId} />
          <Lines c={c} caseId={props.caseId} onResubmitted={props.onResubmitted} />
          <LetterCard c={c} caseId={props.caseId} included={included} />
          <Rehearse c={c} caseId={props.caseId} />
          <Survey caseId={props.caseId} />
          <div className="card actions-card">
            <NewAndDelete onNewBill={props.onNewBill} onDelete={props.onDelete} />
          </div>
        </>
      ) : null}
    </section>
  );
}

function NewAndDelete(props: { onNewBill: () => void; onDelete: () => void }) {
  const { ts } = useApp();
  return (
    <>
      <button id="new-bill" type="button" onClick={props.onNewBill}>{ts("new_bill")}</button>
      <button id="delete-case" type="button" className="danger" onClick={props.onDelete}>{ts("delete_now")}</button>
    </>
  );
}

// --- Summary ----------------------------------------------------------------------------------

function Summary({ c }: { c: CaseData }) {
  const { lang, t, ts } = useApp();
  const bill = c.bill!;
  const rows: [string, string, string?][] = [
    [t("sum_provider"), bill.provider_name || "—"],
    [t("sum_statement_date"), shortDate(bill.statement_date, lang)],
    [t("sum_total_charges"), money(bill.totals.billed)],
    [t("sum_adjustments"), money(bill.totals.adjustments)],
    [t("sum_amount_due"), money(bill.totals.patient_balance), "strong"],
  ];
  if (c.eob) rows.push([t("sum_insurer_says"), money(c.eob.totals.patient_responsibility), "strong"]);
  const eobProblem = c.eob_status === "unreadable" || c.eob_status === "partial";
  const hardToRead = ((c.warnings ?? []).length > 0 || bill.extraction_confidence === "low") && !c.user_edited;

  return (
    <div className="card">
      <h2>{ts("summary_title")}</h2>
      <dl id="summary" className="summary">
        {rows.map(([k, v, cls]) => (
          <div key={k} className="summary-row">
            <dt>{k}</dt>
            <dd className={cls}>{v}</dd>
          </div>
        ))}
      </dl>
      <p id="eob-note" className="note" hidden={!eobProblem}>
        {c.eob_status === "partial" ? t("eob_partial") : t("eob_unreadable")}
      </p>
      <p id="warning-note" className="note" hidden={!hardToRead}>{ts("warning_note")}</p>
      <p id="edited-note" className="note" hidden={!c.user_edited}>{ts("edited_note")}</p>
      <details className="glossary">
        <summary>{ts("glossary_title")}</summary>
        <dl id="glossary">
          {GLOSSARY[lang].map(([term, def]) => (
            <div key={term}>
              <dt>{term}</dt>
              <dd>{def}</dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  );
}

// --- Flags ------------------------------------------------------------------------------------

function Flags(props: { c: CaseData; caseId: string; included: Set<string>; setIncluded: (s: Set<string>) => void }) {
  const { t, ts } = useApp();
  const flags = props.c.flags ?? [];
  const expl = props.c.explanations?.flags ?? {};
  const toggle = (id: string, on: boolean) => {
    const next = new Set(props.included);
    if (on) next.add(id);
    else next.delete(id);
    props.setIncluded(next);
  };
  return (
    <div className="card">
      <h2 id="flags-heading">{ts("flags_title")}</h2>
      <p id="flags-intro" className="muted" hidden={flags.length === 0}>{ts("flags_intro")}</p>
      <div id="flags">
        {flags.length === 0 ? (
          <p className="none-found">{props.c.eob ? t("none_found_eob") : t("none_found_no_eob")}</p>
        ) : (
          flags.map((f) => (
            <FlagCard key={f.flag_id} f={f} text={expl[f.flag_id]?.text || f.summary} caseId={props.caseId}
              checked={props.included.has(f.flag_id)} onToggle={(on) => toggle(f.flag_id, on)} />
          ))
        )}
      </div>
    </div>
  );
}

function FlagCard(props: { f: Flag; text: string; caseId: string; checked: boolean; onToggle: (on: boolean) => void }) {
  const { t } = useApp();
  const { f } = props;
  const checkboxId = "include-" + f.flag_id.replace(/[^a-zA-Z0-9]/g, "-");
  return (
    <article className="flag">
      <h3>
        {t("rule_" + f.rule)}
        <span className="badge">{t("conf_" + f.confidence)}</span>
      </h3>
      <p>{props.text}</p>
      <ul className="evidence" aria-label={t("evidence")}>
        {f.evidence.map((e, i) => (
          <li key={i}>
            <span className="src">{(e.source === "eob" ? t("src_eob") : t("src_bill")) + (e.page ? t("page", { n: e.page }) : "")}</span>
            <q>{e.text}</q>
          </li>
        ))}
      </ul>
      <label className="include" htmlFor={checkboxId}>
        <input type="checkbox" id={checkboxId} data-flag-id={f.flag_id} checked={props.checked} onChange={(e) => props.onToggle(e.target.checked)} />
        {t("include_letter")}
      </label>
      <Feedback caseId={props.caseId} flagId={f.flag_id} />
    </article>
  );
}

function Feedback(props: { caseId: string; flagId: string }) {
  const { t, call, setError } = useApp();
  const [chosen, setChosen] = useState<string | null>(null);
  const send = async (verdict: string) => {
    try {
      await call("POST", "/api/cases/" + props.caseId + "/feedback", { flag_id: props.flagId, verdict });
      setChosen(verdict);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <div className="feedback">
      <span className="feedback-q">{t("was_right")}</span>
      {["correct", "incorrect", "unsure"].map((v) => (
        <button key={v} type="button" className="small" aria-pressed={chosen === v} onClick={() => send(v)}>
          {t("verdict_" + v)}
        </button>
      ))}
      <span className="thanks" role="status">{chosen ? t("thanks") : ""}</span>
    </div>
  );
}

// --- Ask a question (RAG) ----------------------------------------------------------------------

function Ask(props: { caseId: string }) {
  const { lang, t, tl, ts, call, setError } = useApp();
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AskResult | null>(null);
  const [asked, setAsked] = useState(false);

  useEffect(() => {
    setResult(null);
    setAsked(false);
    setQuestion("");
  }, [props.caseId]);

  const ask = async (q: string) => {
    setError("");
    if (!q.trim()) return setError(t("err_question"));
    setBusy(true);
    setAsked(true);
    setResult(null);
    try {
      setResult(await call<AskResult>("POST", "/api/ask", { question: q.trim(), case_id: props.caseId, language: lang }));
    } catch (e) {
      setAsked(false);
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const list = result ? (result.fallback ? result.related : result.sources) : [];
  return (
    <div className="card" id="ask-card">
      <h2>{ts("ask_title")}</h2>
      <p className="muted">{ts("ask_intro")}</p>
      <div id="ask-examples" className="examples">
        {tl("ask_examples").map((q) => (
          <button key={q} type="button" className="small" onClick={() => { setQuestion(q); ask(q); }}>
            {q}
          </button>
        ))}
      </div>
      <form id="ask-form" noValidate onSubmit={(e) => { e.preventDefault(); ask(question); }}>
        <label htmlFor="ask-input">{ts("ask_label")}</label>
        <textarea id="ask-input" rows={2} maxLength={500} value={question} onChange={(e) => setQuestion(e.target.value)} />
        <button type="submit" className="primary" disabled={busy}>{ts("ask_button")}</button>
      </form>
      <div id="ask-answer" hidden={!asked}>
        <p id="ask-text" className="answer" aria-live="polite">{busy ? t("asking") : result?.answer}</p>
        <h3 id="ask-sources-title" hidden={list.length === 0}>{result?.fallback ? t("ask_related") : ts("ask_sources")}</h3>
        <ul id="ask-sources" className="sources">
          {list.map((s, i) => (
            <SourceItem key={i} s={s} />
          ))}
        </ul>
        <p className="hint">{ts("ask_disclaimer")}</p>
      </div>
    </div>
  );
}

function SourceItem({ s }: { s: Source }) {
  const safe = /^https:\/\//.test(s.source_url || "");
  return (
    <li>
      <span className="source-title">{s.title + " — " + s.section}</span>
      {s.source_name ? (
        <span className="source-from">
          {" · "}
          {safe ? (
            <a href={s.source_url} target="_blank" rel="noopener noreferrer">{s.source_name}</a>
          ) : (
            s.source_name
          )}
        </span>
      ) : null}
    </li>
  );
}

// --- Lines and editing ----------------------------------------------------------------------

interface EditRow {
  key: number;
  line_id: string | null;
  service_date: string;
  code: string;
  description: string;
  units: string;
  charge: string;
}

let rowKey = 0;
const toRow = (li?: LineItem): EditRow => ({
  key: rowKey++,
  line_id: li?.line_id ?? null,
  service_date: li?.service_date ?? "",
  code: li?.code ?? "",
  description: li?.description ?? "",
  units: li?.units ?? "",
  charge: li?.charge ?? "",
});

function Lines(props: { c: CaseData; caseId: string; onResubmitted: (id: string) => void }) {
  const { lang, t, ts, call, setError } = useApp();
  const bill = props.c.bill!;
  const expl = props.c.explanations?.lines ?? {};
  const prices = props.c.price_context ?? {};
  const [editing, setEditing] = useState(false);
  const [rows, setRows] = useState<EditRow[]>([]);
  const [totals, setTotals] = useState({ billed: "", adjustments: "", balance: "" });

  useEffect(() => setEditing(false), [props.c]);

  const open = () => {
    setRows(bill.line_items.map(toRow));
    setTotals({ billed: bill.totals.billed ?? "", adjustments: bill.totals.adjustments ?? "", balance: bill.totals.patient_balance ?? "" });
    setEditing(true);
  };

  const update = (key: number, field: keyof EditRow, value: string) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, [field]: value } : r)));

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const amount = (v: string) => parseAmount(v, t("err_amount_format"));
      const lines = rows.map((r, i) => {
        if (!r.description.trim()) throw new Error(t("err_line_desc", { n: i + 1 }));
        const charge = amount(r.charge);
        if (charge === null) throw new Error(t("err_line_charge", { n: i + 1 }));
        if (r.units.trim() && !/^\d+(\.\d+)?$/.test(r.units.trim())) throw new Error(t("err_line_units", { n: i + 1 }));
        return {
          line_id: r.line_id,
          service_date: r.service_date || null,
          description: r.description.trim(),
          code: r.code.trim() || null,
          units: r.units.trim() || null,
          charge,
        };
      });
      const body = {
        line_items: lines,
        totals: { billed: amount(totals.billed), adjustments: amount(totals.adjustments), patient_balance: amount(totals.balance) },
      };
      await call("PUT", "/api/cases/" + props.caseId + "/bill", body);
      props.onResubmitted(props.caseId);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="card">
      <div className="card-head">
        <h2>{ts("lines_title")}</h2>
        <button id="edit-lines" type="button" className="small" hidden={editing} onClick={open}>{ts("fix_mistake")}</button>
      </div>
      <form id="edit-form" hidden={!editing} noValidate onSubmit={save}>
        <p className="hint">{ts("edit_hint")}</p>
        <div id="edit-rows">
          {rows.map((r) => (
            <fieldset key={r.key} className="edit-row">
              <EditCell label={t("edit_date")} name="service_date" type="date" value={r.service_date} onChange={(v) => update(r.key, "service_date", v)} />
              <EditCell label={t("edit_code")} name="code" value={r.code} maxLength={20} onChange={(v) => update(r.key, "code", v)} />
              <EditCell label={t("edit_service")} name="description" value={r.description} maxLength={300} onChange={(v) => update(r.key, "description", v)} />
              <EditCell label={t("edit_units")} name="units" value={r.units} inputMode="decimal" onChange={(v) => update(r.key, "units", v)} />
              <EditCell label={t("edit_charge")} name="charge" value={r.charge} inputMode="decimal" onChange={(v) => update(r.key, "charge", v)} />
              <button type="button" className="small danger" aria-label={t("remove_line")} onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}>
                {t("remove")}
              </button>
            </fieldset>
          ))}
        </div>
        <button id="add-line" type="button" className="small" onClick={() => setRows((rs) => [...rs, toRow()])}>{ts("add_line")}</button>
        <div className="field-row three">
          <div className="field">
            <label htmlFor="edit-billed">{ts("total_charges")}</label>
            <input id="edit-billed" type="text" inputMode="decimal" value={totals.billed} onChange={(e) => setTotals({ ...totals, billed: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="edit-adjust">{ts("payments_adjustments")}</label>
            <input id="edit-adjust" type="text" inputMode="decimal" value={totals.adjustments} onChange={(e) => setTotals({ ...totals, adjustments: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="edit-balance">{ts("amount_due")}</label>
            <input id="edit-balance" type="text" inputMode="decimal" value={totals.balance} onChange={(e) => setTotals({ ...totals, balance: e.target.value })} />
          </div>
        </div>
        <div className="actions">
          <button type="submit" className="primary">{ts("save_check")}</button>
          <button id="edit-cancel" type="button" onClick={() => setEditing(false)}>{ts("cancel")}</button>
        </div>
      </form>
      <div className="table-wrap" id="lines-wrap" hidden={editing}>
        <table id="lines">
          <thead>
            <tr>
              <th scope="col" className="date">{ts("col_date")}</th>
              <th scope="col">{ts("col_service")}</th>
              <th scope="col" className="num">{ts("col_charge")}</th>
            </tr>
          </thead>
          <tbody>
            {bill.line_items.length === 0 ? (
              <tr>
                <td colSpan={3} className="muted">{t("no_lines")}</td>
              </tr>
            ) : (
              bill.line_items.map((li) => {
                const e = expl[li.line_id];
                const units = li.units && Number(li.units) !== 1 ? " × " + li.units : "";
                const ref = prices[li.line_id];
                return (
                  <tr key={li.line_id}>
                    <td className="date">{shortDate(li.service_date, lang)}</td>
                    <td>
                      <div className="line-desc">{li.description}</div>
                      <div className="line-date">{shortDate(li.service_date, lang)}</div>
                      {li.code ? <div className="line-code">{t("code", { code: li.code }) + units}</div> : null}
                      {e && e.source === "llm" ? <div className="line-expl">{e.text}</div> : null}
                      {ref ? <div className="line-ref">{t("reference_price", { label: props.c.prices_label ?? "", price: money(ref.reference_price) })}</div> : null}
                    </td>
                    <td className="num">{money(li.charge)}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EditCell(props: {
  label: string;
  name: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  maxLength?: number;
  inputMode?: "decimal";
}) {
  return (
    <label className={"edit-cell edit-" + props.name}>
      <span>{props.label}</span>
      <input name={props.name} type={props.type ?? "text"} value={props.value} maxLength={props.maxLength} inputMode={props.inputMode}
        onChange={(e) => props.onChange(e.target.value)} />
    </label>
  );
}

// --- Letters ------------------------------------------------------------------------------

type Kind = "dispute" | "itemized_request" | "financial_assistance" | "payment_plan" | "insurer_appeal";

function LetterCard(props: { c: CaseData; caseId: string; included: Set<string> }) {
  const { lang, t, ts, call, setError } = useApp();
  const hasFlags = (props.c.flags ?? []).length > 0;
  const hasDenials = !!props.c.eob?.service_lines.some((sl) => sl.status === "denied" || sl.status === "not_processed");
  const [kind, setKind] = useState<Kind>(hasFlags ? "dispute" : "itemized_request");
  const [f, setF] = useState({ name: "", address: "", phone: "", email: "", account: "", member: "", monthly: "", note: "" });
  const [letter, setLetter] = useState<Letter | null>(null);
  const [lastRequest, setLastRequest] = useState<Record<string, unknown> | null>(null);
  const [copied, setCopied] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);

  useEffect(() => {
    setKind(hasFlags ? "dispute" : "itemized_request");
    setLetter(null);
  }, [props.c.case_id, hasFlags]);

  const set = (key: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [key]: e.target.value });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    const name = f.name.trim();
    if (!name) return setError(t("err_name"));
    const address = f.address.split("\n").map((s) => s.trim()).filter(Boolean);
    if (address.length > 4) return setError(t("err_address"));
    const body: Record<string, unknown> = {
      kind,
      patient: {
        name,
        address_lines: address,
        phone: f.phone.trim() || null,
        email: f.email.trim() || null,
        account_number: f.account.trim() || null,
        member_id: f.member.trim() || null,
      },
      note: f.note.trim() || null,
    };
    try {
      if (kind === "payment_plan") body.monthly_amount = parseAmount(f.monthly, t("err_amount_format"));
      if (kind === "dispute") {
        body.flag_ids = (props.c.flags ?? []).map((x) => x.flag_id).filter((id) => props.included.has(id));
        if (!(body.flag_ids as string[]).length) return setError(t("err_tick"));
      }
      setLetter(await call<Letter>("POST", "/api/cases/" + props.caseId + "/letter", body));
      setLastRequest(body);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const filename = (ext: string) => (letter ? letter.kind.replace(/_/g, "-") : "letter") + "." + ext;

  const copy = async () => {
    if (!letter) return;
    try {
      await navigator.clipboard.writeText(letter.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError(t("err_copy"));
    }
  };

  const downloadPdf = async () => {
    if (!lastRequest) return;
    setPdfBusy(true);
    try {
      saveBlob(await apiBlob("/api/cases/" + props.caseId + "/letter", { ...lastRequest, format: "pdf" }), filename("pdf"));
    } catch (e) {
      setError(e instanceof ApiError && e.code === "demo" ? demoOnly(lang) : t("err_pdf"));
    } finally {
      setPdfBusy(false);
    }
  };

  const radio = (value: Kind, id: string, label: string, extra: { disabled?: boolean; hidden?: boolean; labelId?: string } = {}) => (
    <label className="choice" id={extra.labelId} hidden={extra.hidden}>
      <input type="radio" name="kind" value={value} id={id} checked={kind === value} disabled={extra.disabled} onChange={() => setKind(value)} />{" "}
      <span>{ts(label)}</span>
    </label>
  );

  return (
    <div className="card">
      <h2>{ts("letter_title")}</h2>
      <p className="muted">{ts("letter_intro")}</p>
      <form id="letter-form" noValidate onSubmit={submit}>
        <fieldset className="field">
          <legend>{ts("letter_type")}</legend>
          {radio("dispute", "kind-dispute", "kind_dispute", { disabled: !hasFlags })}
          {radio("itemized_request", "kind-itemized", "kind_itemized")}
          {radio("financial_assistance", "kind-assistance", "kind_assistance")}
          {radio("payment_plan", "kind-plan", "kind_plan")}
          {radio("insurer_appeal", "kind-appeal", "kind_appeal", { hidden: !hasDenials, labelId: "appeal-choice" })}
        </fieldset>
        <p id="dispute-hint" className="hint" hidden={kind !== "dispute"}>{ts("dispute_hint")}</p>
        <p id="assistance-hint" className="hint" hidden={kind !== "financial_assistance"}>{ts("assistance_hint")}</p>
        <div className="field" id="plan-field" hidden={kind !== "payment_plan"}>
          <label htmlFor="p-monthly"><span>{ts("monthly_label")}</span> <span className="opt">{ts("optional")}</span></label>
          <input id="p-monthly" type="text" inputMode="decimal" placeholder={ts("eg_50")} autoComplete="off" value={f.monthly} onChange={set("monthly")} />
        </div>
        <div className="field" id="member-field" hidden={kind !== "insurer_appeal"}>
          <label htmlFor="p-member"><span>{ts("member_label")}</span> <span className="opt">{ts("optional")}</span></label>
          <input id="p-member" type="text" maxLength={50} autoComplete="off" value={f.member} onChange={set("member")} />
          <p className="hint">{ts("member_hint")}</p>
        </div>
        <div className="field">
          <label htmlFor="p-name">{ts("your_name")}</label>
          <input id="p-name" type="text" autoComplete="name" maxLength={200} required value={f.name} onChange={set("name")} />
        </div>
        <div className="field">
          <label htmlFor="p-address"><span>{ts("address_label")}</span> <span className="opt">{ts("optional")}</span></label>
          <textarea id="p-address" rows={3} autoComplete="street-address" placeholder={ts("address_placeholder")} value={f.address} onChange={set("address")} />
        </div>
        <div className="field-row">
          <div className="field">
            <label htmlFor="p-phone"><span>{ts("phone_label")}</span> <span className="opt">{ts("optional")}</span></label>
            <input id="p-phone" type="tel" autoComplete="tel" maxLength={50} value={f.phone} onChange={set("phone")} />
          </div>
          <div className="field">
            <label htmlFor="p-email"><span>{ts("email_label")}</span> <span className="opt">{ts("optional")}</span></label>
            <input id="p-email" type="email" autoComplete="email" maxLength={200} value={f.email} onChange={set("email")} />
          </div>
        </div>
        <div className="field" hidden={kind === "insurer_appeal"}>
          <label htmlFor="p-account"><span>{ts("account_label")}</span> <span className="opt">{ts("optional")}</span></label>
          <input id="p-account" type="text" maxLength={50} autoComplete="off" value={f.account} onChange={set("account")} />
          <p className="hint">{ts("account_hint")}</p>
        </div>
        <div className="field">
          <label htmlFor="p-note"><span>{ts("note_label")}</span> <span className="opt">{ts("optional")}</span></label>
          <textarea id="p-note" rows={3} maxLength={1000} value={f.note} onChange={set("note")} />
        </div>
        <button type="submit" className="primary">{ts("create_letter")}</button>
      </form>
      <div id="letter-output" hidden={!letter}>
        <pre id="letter-text" className="letter" tabIndex={0} lang="en">{letter?.text}</pre>
        <div className="actions">
          <button id="download-pdf" type="button" className="primary" disabled={pdfBusy} onClick={downloadPdf}>{ts("download_pdf")}</button>
          <button id="copy-letter" type="button" onClick={copy}>{copied ? t("copied") : t("copy_text")}</button>
          <button id="download-letter" type="button" onClick={() => letter && saveBlob(new Blob([letter.text], { type: "text/plain;charset=utf-8" }), filename("txt"))}>
            {ts("download_text")}
          </button>
        </div>
      </div>
    </div>
  );
}

// --- Survey -------------------------------------------------------------------------------

function Survey(props: { caseId: string }) {
  const { t, ts, call, setError } = useApp();
  const [helpful, setHelpful] = useState<number | null>(null);
  const [useful, setUseful] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  useEffect(() => {
    setHelpful(null);
    setUseful(null);
    setSent(false);
  }, [props.caseId]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!helpful || !useful) return setError(t("err_answer_both"));
    try {
      await call("POST", "/api/cases/" + props.caseId + "/survey", { helpful, most_useful: useful });
      setError("");
      setSent(true);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const scale: [number, string | null][] = [[1, "helpful_1"], [2, null], [3, null], [4, null], [5, "helpful_5"]];
  return (
    <div className="card" id="survey-card">
      <h2>{ts("survey_title")}</h2>
      <form id="survey-form" noValidate onSubmit={submit}>
        <fieldset className="field">
          <legend>{ts("survey_helpful")}</legend>
          <div className="scale">
            {scale.map(([n, key]) => (
              <label key={n} className="choice">
                <input type="radio" name="helpful" value={n} checked={helpful === n} onChange={() => setHelpful(n)} /> {key ? ts(key) : n}
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className="field">
          <legend>{ts("survey_most")}</legend>
          {["explanation", "letter", "both", "neither"].map((v) => (
            <label key={v} className="choice">
              <input type="radio" name="most_useful" value={v} checked={useful === v} onChange={() => setUseful(v)} /> {ts("useful_" + v)}
            </label>
          ))}
        </fieldset>
        <button type="submit">{ts("send")}</button>
        <p id="survey-thanks" className="thanks" hidden={!sent}>{ts("thank_you")}</p>
      </form>
      <p className="hint">{ts("survey_anon")}</p>
    </div>
  );
}
