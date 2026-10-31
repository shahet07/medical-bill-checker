"use client";

import { useEffect, useRef, useState } from "react";
import type { SiteText } from "@/lib/siteText";

// "How it works" as a bill's journey through an isometric town: a big time,
// the logo pin moving between places along a path, a phone showing that
// moment, and a timeline. Plays while on screen; clicking a time takes over.

const STEP_MS = 4200;

// Isometric projection: grid (i, j) on the ground, k up. Screen units in the SVG viewBox.
const S = 40;
const OX = 560;
const OY = 66;
const pt = (i: number, j: number, k = 0): [number, number] => [OX + (i - j) * S * 0.866, OY + (i + j) * S * 0.5 - k * S];
const poly = (pts: [number, number, number][]) => pts.map(([i, j, k]) => pt(i, j, k).map((v) => v.toFixed(1)).join(",")).join(" ");

/** A box on the ground (or at height z): top, left (+j) and right (+i) faces. */
function Box(props: { i: number; j: number; w: number; d: number; h: number; z?: number; tone?: string; className?: string }) {
  const { i, j, w, d, h } = props;
  const z = props.z ?? 0;
  const t = z + h;
  return (
    <g className={"iso " + (props.tone ?? "base") + (props.className ? " " + props.className : "")}>
      <polygon className="f-l" points={poly([[i, j + d, z], [i + w, j + d, z], [i + w, j + d, t], [i, j + d, t]])} />
      <polygon className="f-r" points={poly([[i + w, j, z], [i + w, j + d, z], [i + w, j + d, t], [i + w, j, t]])} />
      <polygon className="f-t" points={poly([[i, j, t], [i + w, j, t], [i + w, j + d, t], [i, j + d, t]])} />
    </g>
  );
}

/** Rows of windows on a building's two visible faces. */
function Windows(props: { i: number; j: number; w: number; d: number; rows: number[] }) {
  const { i, j, w, d } = props;
  return (
    <g className="iso-windows">
      {props.rows.map((k) => (
        <g key={k}>
          <polygon points={poly([[i + 0.25, j + d, k], [i + w - 0.25, j + d, k], [i + w - 0.25, j + d, k + 0.22], [i + 0.25, j + d, k + 0.22]])} />
          <polygon points={poly([[i + w, j + 0.25, k], [i + w, j + d - 0.25, k], [i + w, j + d - 0.25, k + 0.22], [i + w, j + 0.25, k + 0.22]])} />
        </g>
      ))}
    </g>
  );
}

function Person(props: { i: number; j: number; tone: string }) {
  const [x, y] = pt(props.i, props.j);
  return (
    <g className={"iso-person " + props.tone}>
      <ellipse cx={x} cy={y} rx="7" ry="3.5" className="shadow" />
      <rect x={x - 5} y={y - 22} width="10" height="20" rx="5" />
      <circle cx={x} cy={y - 28} r="5" />
    </g>
  );
}

// Where the pin stops (ground points), in the order of the story.
const STOPS: [number, number][] = [
  [5.9, 3.0], // mailbox
  [9.4, 3.9], // insurer
  [3.4, 7.2], // kitchen table
  [7.0, 7.6], // Clyvexa
  [10.4, 11.6], // billing office
  [5.9, 3.0], // mailbox again
];
// The building that lights up at each stop.
const LIT = ["home", "insurer", "table", "hub", "hospital", "home"];

function Scene({ step }: { step: number }) {
  const pin = useRef<SVGGElement>(null);
  const ring = useRef<SVGGElement>(null);
  useEffect(() => {
    const [x, y] = pt(...STOPS[step]);
    if (pin.current) pin.current.style.transform = `translate(${x}px, ${y}px)`;
    if (ring.current) ring.current.style.transform = `translate(${x}px, ${y}px)`;
  }, [step]);
  const lit = (name: string) => (LIT[step] === name ? " lit" : "");
  const segs = STOPS.slice(1).map((b, n) => [STOPS[n], b] as const);

  return (
    <svg viewBox="0 0 1040 700" className="iso-scene" aria-hidden="true">
      {/* the ground slab */}
      <g className="iso slab">
        <polygon className="f-l" points={poly([[0, 13, 0], [13, 13, 0], [13, 13, -0.5], [0, 13, -0.5]])} />
        <polygon className="f-r" points={poly([[13, 0, 0], [13, 13, 0], [13, 13, -0.5], [13, 0, -0.5]])} />
        <polygon className="f-t" points={poly([[0, 0, 0], [13, 0, 0], [13, 13, 0], [0, 13, 0]])} />
      </g>
      {/* lawn and plaza patches */}
      <polygon className="iso-patch" points={poly([[0.8, 0.6, 0], [6.6, 0.6, 0], [6.6, 4.6, 0], [0.8, 4.6, 0]])} />
      <polygon className="iso-patch" points={poly([[1.8, 5.6, 0], [4.8, 5.6, 0], [4.8, 8.6, 0], [1.8, 8.6, 0]])} />
      <polygon className="iso-patch blue" points={poly([[5.4, 5.6, 0], [8.6, 5.6, 0], [8.6, 8.8, 0], [5.4, 8.8, 0]])} />

      {/* paths: all faint, travelled ones solid */}
      {segs.map(([a, b], n) => {
        const [x1, y1] = pt(...a);
        const [x2, y2] = pt(...b);
        const cls = n < step - 1 ? " done" : n === step - 1 ? " now" : "";
        return (
          <g key={n}>
            <line className="iso-path" x1={x1} y1={y1} x2={x2} y2={y2} />
            <line className={"iso-path-on" + cls} x1={x1} y1={y1} x2={x2} y2={y2} pathLength={1} key={step + "-" + n} />
          </g>
        );
      })}

      {/* home: house with a gable roof, mailbox */}
      <g className={"place" + lit("home")}>
        <Box i={1.4} j={1.2} w={3.2} d={2.6} h={1.7} />
        <Windows i={1.4} j={1.2} w={3.2} d={2.6} rows={[0.7]} />
        <g className="iso base">
          <polygon className="f-t" points={poly([[1.4, 1.2, 1.7], [4.6, 1.2, 1.7], [4.6, 2.5, 2.7], [1.4, 2.5, 2.7]])} />
          <polygon className="f-r" points={poly([[4.6, 1.2, 1.7], [4.6, 3.8, 1.7], [4.6, 2.5, 2.7]])} />
          <polygon className="f-l roof" points={poly([[1.4, 3.8, 1.7], [4.6, 3.8, 1.7], [4.6, 2.5, 2.7], [1.4, 2.5, 2.7]])} />
        </g>
        <Box i={5.82} j={2.62} w={0.12} d={0.12} h={0.7} tone="dark" />
        <Box i={5.6} j={2.45} w={0.55} d={0.4} h={0.32} z={0.7} tone="accent" />
      </g>

      {/* insurer: a tower */}
      <g className={"place" + lit("insurer")}>
        <Box i={7.6} j={1.0} w={2.1} d={2.2} h={4.4} />
        <Windows i={7.6} j={1.0} w={2.1} d={2.2} rows={[0.6, 1.4, 2.2, 3.0, 3.8]} />
      </g>

      {/* kitchen table with two chairs */}
      <g className={"place" + lit("table")}>
        <Box i={2.6} j={6.2} w={1.4} d={0.9} h={0.5} />
        <Box i={2.2} j={6.4} w={0.3} d={0.4} h={0.3} tone="dark" />
        <Box i={4.15} j={6.4} w={0.3} d={0.4} h={0.3} tone="dark" />
        <Box i={3.0} j={6.45} w={0.42} d={0.3} h={0.06} z={0.5} tone="accent" />
      </g>

      {/* Clyvexa: a low building with a screen on top */}
      <g className={"place" + lit("hub")}>
        <Box i={5.9} j={6.1} w={2.0} d={2.0} h={1.0} tone="brand" />
        <Box i={6.3} j={6.5} w={1.2} d={1.2} h={0.08} z={1.0} tone="screen" />
      </g>

      {/* hospital billing office, with a cross on the roof */}
      <g className={"place" + lit("hospital")}>
        <Box i={9.5} j={8.6} w={2.8} d={2.3} h={2.5} />
        <Windows i={9.5} j={8.6} w={2.8} d={2.3} rows={[0.6, 1.4]} />
        <Box i={10.7} j={9.4} w={0.4} d={1.2} h={0.18} z={2.5} tone="mint" />
        <Box i={10.3} j={9.8} w={1.2} d={0.4} h={0.18} z={2.5} tone="mint" />
      </g>

      {/* trees and people */}
      <Box i={0.7} j={10.2} w={0.8} d={0.8} h={0.8} tone="mint" />
      <Box i={11.2} j={4.6} w={0.8} d={0.8} h={0.8} tone="mint" />
      <Box i={5.6} j={11.2} w={0.7} d={0.7} h={0.7} tone="mint" />
      <Box i={12.0} j={5.8} w={0.6} d={0.6} h={0.6} tone="mint" />
      <Person i={3.3} j={7.6} tone="amber" />
      <Person i={11.0} j={11.7} tone="blue" />
      <Person i={9.6} j={4.3} tone="soft" />
      <Person i={12.4} j={7.2} tone="mint" />

      {/* the moving pin: a ring on the ground, the logo above it */}
      <g ref={ring} className="iso-ring">
        <ellipse cx="0" cy="0" rx="26" ry="13" />
      </g>
      <g ref={pin} className="iso-pin">
        <g className="bob">
          <path d="M0 -6 L-9 -22 H9 Z" className="stem" />
          <rect x="-30" y="-82" width="60" height="60" rx="18" className="bubble" />
          <image href="/icon.svg" x="-21" y="-73" width="42" height="42" />
        </g>
      </g>
    </svg>
  );
}

function Screen({ s, step }: { s: SiteText; step: number }) {
  const j = s.journey;
  const st = j.stops[step];
  return (
    <div className="phone" aria-hidden="true">
      <div className="phone-notch" />
      <div className="phone-body" key={step}>
        <span className="phone-tag">{j.example}</span>
        {(step === 0 || step === 1 || step === 5) && (
          <div className="ps-doc">
            <small>{st.head}</small>
            <strong className={step === 0 ? "warn" : "ok"}>{st.big}</strong>
            <span>{st.sub}</span>
            <i />
            <i />
            <i className="short" />
            {st.ok && <em className="ps-ok">✓ {st.ok}</em>}
          </div>
        )}
        {step === 2 && (
          <div className="ps-camera">
            <div className="viewfinder">
              <b />
              <b />
              <b />
              <b />
              <div className="paper">
                <i />
                <i />
                <i className="amber" />
                <i />
              </div>
            </div>
            <em className="ps-ok">✓ {st.ok}</em>
          </div>
        )}
        {step === 3 && (
          <div className="ps-flags">
            <small>{s.mock.title}</small>
            <div className="ps-flag">{s.mock.badges[0]}</div>
            <div className="ps-flag">{s.mock.badges[1]}</div>
            <strong className="ok">
              {s.mock.owed[0]}
              <b>$315.60</b>
              {s.mock.owed[1]}
            </strong>
            <span className="ps-btn">{s.mock.letter}</span>
          </div>
        )}
        {step === 4 && (
          <div className="ps-call">
            <div className="b you">{s.bento.rehearse.youLine}</div>
            <div className="b rep">{j.reply}</div>
          </div>
        )}
      </div>
    </div>
  );
}

// Scroll-driven when the pinned scene fits the window (see the matching media query in site.css).
const SCROLL_MODE = "(min-width: 900px) and (min-height: 620px) and (prefers-reduced-motion: no-preference)";

export default function Journey({ s }: { s: SiteText }) {
  const stops = s.journey.stops;
  const n = stops.length;
  const [step, setStep] = useState(0);
  const [scrollMode, setScrollMode] = useState(false);
  const [auto, setAuto] = useState(true);
  const [visible, setVisible] = useState(false);
  const outer = useRef<HTMLDivElement>(null);
  const line = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const mq = window.matchMedia(SCROLL_MODE);
    const update = () => setScrollMode(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  /** How far through the pinned stretch the reader has scrolled, 0..1. */
  const progress = () => {
    const el = outer.current;
    if (!el) return 0;
    const pin = el.firstElementChild as HTMLElement;
    const total = el.offsetHeight - pin.offsetHeight;
    return total > 0 ? Math.min(1, Math.max(0, -el.getBoundingClientRect().top / total)) : 0;
  };
  const setBar = (fraction: number) => line.current?.style.setProperty("--p", String(Math.min(1, Math.max(0, fraction))));

  // Scroll mode: the scroll position picks the step and fills the timeline bar.
  useEffect(() => {
    if (!scrollMode) return;
    let frame = 0;
    const onScroll = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const pr = progress();
        setStep(Math.min(n - 1, Math.floor(pr * n)));
        setBar((pr * n - 0.5) / (n - 1));
      });
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [scrollMode, n]);

  // Otherwise (small screens, reduced motion): play on a timer while visible.
  useEffect(() => {
    if (scrollMode) return;
    const el = outer.current;
    if (!el || !("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting), { threshold: 0.35 });
    io.observe(el);
    return () => io.disconnect();
  }, [scrollMode]);
  useEffect(() => {
    if (scrollMode) return;
    setBar(step / (n - 1));
    if (!auto || !visible || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const t = window.setTimeout(() => setStep((x) => (x + 1) % n), STEP_MS);
    return () => window.clearTimeout(t);
  }, [scrollMode, step, auto, visible, n]);

  const choose = (i: number) => {
    const el = outer.current;
    if (scrollMode && el) {
      // Scroll to the middle of that step's stretch; the scroll handler does the rest.
      const pin = el.firstElementChild as HTMLElement;
      const total = el.offsetHeight - pin.offsetHeight;
      const top = el.getBoundingClientRect().top + window.scrollY + ((i + 0.5) / n) * total;
      window.scrollTo({ top, behavior: "smooth" });
    } else {
      setStep(i);
      setAuto(false);
    }
  };

  const st = stops[step];
  return (
    <div className="journey-scroll" ref={outer}>
      <div className="journey-pin">
        <div className="site-wrap">
          <div className="journey">
            <div className="journey-head">
              <p className="kicker">
                {s.journey.label} · {s.journey.example}
              </p>
              <p className="journey-time display" key={"t" + step}>
                {st.time}
              </p>
              <h3 key={"h" + step} className="fade-swap">
                {st.title}
              </h3>
              <p className="journey-place fade-swap" key={"p" + step}>
                {st.place}
              </p>
            </div>
            <div className="journey-stage">
              <Scene step={step} />
              <Screen s={s} step={step} />
            </div>
            <ol className="journey-line" ref={line} aria-label={s.journey.title}>
              {stops.map((x, i) => (
                <li key={x.short} className={(i < step ? "past" : "") + (i === step ? " now" : "")}>
                  <button type="button" onClick={() => choose(i)} aria-current={i === step ? "step" : undefined} aria-label={x.time + ": " + x.title}>
                    <span className="dot" aria-hidden="true" />
                    <span className="lbl">{x.short}</span>
                  </button>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </div>
    </div>
  );
}
