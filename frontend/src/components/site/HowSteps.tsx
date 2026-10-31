"use client";

import { useEffect, useState } from "react";
import type { SiteText } from "@/lib/siteText";
import Icon from "./Icon";

const STEP_MS = 6000;
const STEP_ICONS = ["upload", "eye", "send"];

/** "How it works": a timeline that moves through the three steps (or follows clicks), with a picture of each. */
export default function HowSteps({ s }: { s: SiteText }) {
  const [step, setStep] = useState(0);
  const [auto, setAuto] = useState(true);

  useEffect(() => {
    if (!auto || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const t = window.setTimeout(() => setStep((step + 1) % 3), STEP_MS);
    return () => window.clearTimeout(t);
  }, [step, auto]);

  const choose = (i: number) => {
    setStep(i);
    setAuto(false);
  };
  const h = s.how;
  return (
    <div className="how">
      <div className="how-copy">
        <span className="how-num" aria-hidden="true">
          0{step + 1}
        </span>
        <h3 key={"t" + step} className="fade-swap">
          {h.steps[step].title}
        </h3>
        <p key={"b" + step} className="fade-swap">
          {h.steps[step].body}
        </p>
        <ol className="timeline" aria-label={h.label}>
          {h.steps.map((st, i) => (
            <li key={st.title} className={(i < step ? "past" : "") + (i === step ? " now" : "")}>
              <button type="button" onClick={() => choose(i)} aria-current={i === step ? "step" : undefined}>
                <span className="node" aria-hidden="true">
                  <Icon name={STEP_ICONS[i]} />
                </span>
                {st.title}
              </button>
              {i < 2 && (
                <span className="track" aria-hidden="true">
                  <span className={"fill" + (i < step ? " full" : i === step && auto ? " run" : "")} key={step + "-" + i} />
                </span>
              )}
            </li>
          ))}
        </ol>
      </div>

      <div className="device" aria-hidden="true">
        <div className="device-bar">
          <i />
          <i />
          <i />
          <span>clyvexa</span>
        </div>
        <div className="device-screen" key={step}>
          {step === 0 && (
            <div className="pane pane-upload">
              <div className="drop">
                <Icon name="upload" />
              </div>
              {h.upload.files.map((f, i) => (
                <div className="file" key={f}>
                  <span className="file-name">{f}</span>
                  <span className="file-bar">
                    <i className={"d" + i} />
                  </span>
                  <span className={"file-ok d" + i}>✓ {h.upload.ok}</span>
                </div>
              ))}
            </div>
          )}
          {step === 1 && (
            <div className="pane pane-confirm">
              {s.mock.bill.lines.map((l, i) => (
                <div className={"line" + (i === 2 ? " editing" : "")} key={i}>
                  <span>
                    {l.desc}
                    {i === 2 && <i className="caret" />}
                  </span>
                  <span>{l.amt}</span>
                  {i === 2 && <em>{h.confirm.edit}</em>}
                </div>
              ))}
              <span className="pane-btn">{h.confirm.button}</span>
            </div>
          )}
          {step === 2 && (
            <div className="pane pane-act">
              <div className="letter-head">
                <strong>{h.act.letter}</strong>
                <svg viewBox="0 0 7 7" className="qr-small">
                  <rect x="0" y="0" width="3" height="3" />
                  <rect x="4" y="0" width="3" height="3" />
                  <rect x="0" y="4" width="3" height="3" />
                  <rect x="4" y="4" width="1" height="1" />
                  <rect x="6" y="5" width="1" height="2" />
                </svg>
              </div>
              <p className="greeting">{h.act.greeting}</p>
              <i className="ln w90" />
              <i className="ln w80" />
              <i className="ln w95 hl" />
              <i className="ln w60" />
              <div className="pane-actions">
                <span className="pane-btn">{h.act.pdf}</span>
                <span className="pane-btn ghost">{h.act.copy}</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
