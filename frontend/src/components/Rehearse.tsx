"use client";

import { useEffect, useRef, useState } from "react";
import { useApp } from "@/lib/app";
import type { CaseData, Source } from "@/lib/types";

type Counterpart = "billing_office" | "insurer";
interface Turn {
  role: "patient" | "rep";
  text: string;
}
interface Score {
  scores: Record<string, number>;
  strengths: string[];
  improvements: string[];
  try_saying: string[];
  sources: Source[];
  fallback: boolean;
  tips: string[];
}

const SKILLS = ["clarity", "evidence", "asks", "persistence"];

// Practice call: the transcript lives only in this component and is sent with each turn.
export default function Rehearse(props: { c: CaseData; caseId: string }) {
  const { lang, t, call, setError } = useApp();
  const hasEob = !!props.c.eob;
  const [who, setWho] = useState<Counterpart>("billing_office");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [opener, setOpener] = useState("");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [ended, setEnded] = useState(false);
  const [score, setScore] = useState<Score | null>(null);
  const logRef = useRef<HTMLOListElement>(null);

  const reset = () => {
    setTurns([]);
    setOpener("");
    setInput("");
    setEnded(false);
    setScore(null);
  };
  useEffect(reset, [props.caseId]);
  useEffect(() => {
    logRef.current?.lastElementChild?.scrollIntoView({ block: "nearest" });
  }, [turns.length]);

  const url = "/api/cases/" + props.caseId + "/rehearse";

  const start = async () => {
    setError("");
    reset();
    setBusy(true);
    try {
      const r = await call<{ reply: string; suggested_opener: string }>("POST", url, { counterpart: who, turns: [], language: lang });
      setTurns([{ role: "rep", text: r.reply }]);
      setOpener(r.suggested_opener);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const say = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    const text = input.trim();
    if (!text) return setError(t("err_say_something"));
    const next: Turn[] = [...turns, { role: "patient", text }];
    setTurns(next);
    setInput("");
    setBusy(true);
    try {
      const r = await call<{ reply: string; call_ended: boolean }>("POST", url, { counterpart: who, turns: next, language: lang });
      setTurns([...next, { role: "rep", text: r.reply }]);
      setEnded(r.call_ended);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const feedback = async () => {
    setError("");
    setBusy(true);
    try {
      setScore(await call<Score>("POST", url + "/score", { counterpart: who, turns, language: lang }));
      setEnded(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const started = turns.length > 0;
  const spoke = turns.some((x) => x.role === "patient");
  return (
    <div className="card" id="rehearse-card">
      <h2>{t("rehearse_title")}</h2>
      <p className="muted">{t("rehearse_intro")}</p>

      {!started ? (
        <div id="rehearse-setup">
          <fieldset className="field">
            <legend>{t("rehearse_who")}</legend>
            <label className="choice">
              <input type="radio" name="counterpart" id="rehearse-billing" checked={who === "billing_office"} onChange={() => setWho("billing_office")} />{" "}
              {t("rehearse_billing")}
            </label>
            <label className="choice" hidden={!hasEob}>
              <input type="radio" name="counterpart" id="rehearse-insurer" checked={who === "insurer"} onChange={() => setWho("insurer")} />{" "}
              {t("rehearse_insurer")}
            </label>
          </fieldset>
          <button id="rehearse-start" type="button" className="primary" disabled={busy} onClick={start}>
            {t("rehearse_start")}
          </button>
        </div>
      ) : (
        <>
          <ol id="rehearse-log" className="call-log" ref={logRef} aria-live="polite">
            {turns.map((turn, i) => (
              <li key={i} className={"turn turn-" + turn.role}>
                <span className="turn-who">{turn.role === "rep" ? t("rehearse_rep") : t("rehearse_you")}</span>
                <span className="turn-text">{turn.text}</span>
              </li>
            ))}
            {busy && !score ? (
              <li className="turn turn-rep">
                <span className="turn-who">{t("rehearse_rep")}</span>
                <span className="turn-text">{t("rehearse_thinking")}</span>
              </li>
            ) : null}
          </ol>

          {opener && !spoke ? (
            <p className="hint" id="rehearse-opener">
              {t("rehearse_try_line")} <q>{opener}</q>{" "}
              <button type="button" className="link" onClick={() => setInput(opener)}>{t("rehearse_use_line")}</button>
            </p>
          ) : null}

          {ended && !score ? <p className="note">{t("rehearse_ended")}</p> : null}

          {!score ? (
            <form id="rehearse-form" noValidate onSubmit={say}>
              <label htmlFor="rehearse-input">{t("rehearse_input")}</label>
              <textarea id="rehearse-input" rows={2} maxLength={600} value={input} disabled={ended} onChange={(e) => setInput(e.target.value)} />
              <div className="actions">
                <button type="submit" className="primary" disabled={busy || ended}>{t("rehearse_send")}</button>
                <button id="rehearse-score" type="button" disabled={busy || !spoke} onClick={feedback}>{t("rehearse_feedback")}</button>
              </div>
            </form>
          ) : null}

          {score ? <ScoreView score={score} /> : null}

          <button id="rehearse-restart" type="button" className="link" onClick={reset}>{t("rehearse_restart")}</button>
        </>
      )}
      <p className="hint">{t("rehearse_note")}</p>
    </div>
  );
}

function ScoreView({ score }: { score: Score }) {
  const { t } = useApp();
  const list = (key: string, items: string[], id: string) =>
    items.length ? (
      <>
        <h3>{t(key)}</h3>
        <ul id={id}>{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
      </>
    ) : null;
  return (
    <div id="rehearse-result" className="score">
      {!score.fallback ? (
        <>
          <h3>{t("rehearse_scores")}</h3>
          <dl className="skills">
            {SKILLS.map((k) => (
              <div key={k} className="skill">
                <dt>{t("rehearse_" + k)}</dt>
                <dd>
                  <meter min={0} max={5} value={score.scores[k] ?? 0} aria-label={t("rehearse_" + k)} /> {score.scores[k]}/5
                </dd>
              </div>
            ))}
          </dl>
        </>
      ) : null}
      {list("rehearse_strengths", score.strengths, "rehearse-strengths")}
      {list("rehearse_improvements", score.improvements.length ? score.improvements : score.tips, "rehearse-improvements")}
      {score.try_saying.length ? (
        <>
          <h3>{t("rehearse_phrases")}</h3>
          <ul id="rehearse-phrases">{score.try_saying.map((x, i) => <li key={i}><q>{x}</q></li>)}</ul>
        </>
      ) : null}
      {score.sources.length ? (
        <ul className="sources">
          {score.sources.map((s, i) => (
            <li key={i}>
              {s.title} · {/^https:\/\//.test(s.source_url) ? <a href={s.source_url} target="_blank" rel="noopener noreferrer">{s.source_name}</a> : s.source_name}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
