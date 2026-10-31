"use client";

import { useEffect, useRef, useState } from "react";
import type { SiteText } from "@/lib/siteText";

// The hero animation: the logo's magnifying glass scans a sample bill line by
// line, flags the duplicate charge and the total that doesn't match the EOB,
// then shows the result. Rows 0-3 are bill lines, row 4 is the amount due.
const TIMELINE: { at: number; ms: number }[] = [
  { at: 0, ms: 1000 },
  { at: 1, ms: 1100 },
  { at: 2, ms: 750 },
  { at: 3, ms: 750 },
  { at: 4, ms: 1200 },
  { at: -1, ms: 5600 }, // done: show the result, then start over
];
const SAVED = 315.6;

function reducedMotion() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export default function HeroScan({ s }: { s: SiteText }) {
  const [step, setStep] = useState(0);
  const [amount, setAmount] = useState(0);
  const [cycle, setCycle] = useState(0);
  const still = useRef(false);

  useEffect(() => {
    if (reducedMotion()) {
      still.current = true;
      setStep(TIMELINE.length - 1);
      setAmount(SAVED);
      return;
    }
    const timer = window.setTimeout(() => {
      if (step === TIMELINE.length - 1) {
        setStep(0);
        setAmount(0);
        setCycle((c) => c + 1);
      } else setStep(step + 1);
    }, TIMELINE[step].ms);
    return () => window.clearTimeout(timer);
  }, [step]);

  const done = TIMELINE[step].at === -1;
  const at = TIMELINE[step].at;
  const reached = done ? 4 : at;

  // Count the savings up once the result appears.
  useEffect(() => {
    if (!done || still.current) return;
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start - 350) / 1100);
      setAmount(t <= 0 ? 0 : SAVED * (1 - Math.pow(1 - t, 3)));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [done]);

  const b = s.mock.bill;
  const rowClass = (i: number) =>
    "scan-row" + (i <= reached ? " seen" : "") + ((i === 1 && reached >= 1) || (i === 4 && reached >= 4) ? " flagged" : "");

  return (
    <figure className={"scan" + (done ? " done" : "")} aria-label={s.mock.label} key={cycle}>
      <div className="scan-paper scan-eob" aria-hidden="true">
        <span>EOB</span>
        <i />
        <i />
        <i />
      </div>
      <div className="scan-card">
        <div className="scan-head">
          <div>
            <strong>{b.provider}</strong>
            <span>{b.statement}</span>
          </div>
          <span className={"scan-status" + (done ? " ok" : "")}>
            <span className="dot" aria-hidden="true" />
            {done ? s.mock.status.checked : s.mock.status.checking}
          </span>
        </div>
        <div className={"scan-rows at-" + (done ? "none" : at)}>
          <div className="scan-lens" aria-hidden="true">
            <svg viewBox="0 0 40 40">
              <path d="M28 12.5A10.5 10.5 0 1 0 28 27.5" />
              <path d="M27.5 29l5 5" />
            </svg>
          </div>
          {b.lines.map((line, i) => (
            <div className={rowClass(i)} key={i}>
              <span>{line.desc}</span>
              <span className="amt">{line.amt}</span>
              {i === 1 && <em className="scan-badge">{s.mock.badges[0]}</em>}
            </div>
          ))}
          <div className={rowClass(4) + " total"}>
            <span>{b.dueLabel}</span>
            <span className="amt">{b.due}</span>
            <em className="scan-badge">{s.mock.badges[1]}</em>
          </div>
        </div>
        <p className="scan-eob-note">{b.eob}</p>
        <div className="scan-result" aria-live="off">
          <svg className="scan-check" viewBox="0 0 48 48" aria-hidden="true">
            <circle cx="24" cy="24" r="21" />
            <path d="M14 25l7 7 13-14" />
          </svg>
          <div>
            <strong>{s.mock.title}</strong>
            <span className="scan-owed">
              {s.mock.owed[0]}
              <b>${amount.toFixed(2)}</b>
              {s.mock.owed[1]}
            </span>
          </div>
          <span className="scan-letter" aria-hidden="true">
            {s.mock.letter}
          </span>
        </div>
      </div>
    </figure>
  );
}
