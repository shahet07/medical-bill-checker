"use client";

import { useEffect, useRef, useState } from "react";

function reducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Fades in `.reveal` elements as they scroll into view. Content stays visible without JavaScript. */
export function useReveal() {
  useEffect(() => {
    if (reducedMotion() || !("IntersectionObserver" in window)) return;
    const root = document.documentElement;
    root.classList.add("reveal-on");
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        }
      },
      { rootMargin: "0px 0px -12% 0px", threshold: 0.12 },
    );
    document.querySelectorAll(".reveal").forEach((el) => io.observe(el));
    return () => {
      io.disconnect();
      root.classList.remove("reveal-on");
    };
  }, []);
}

/** A number that counts up when it scrolls into view. Renders the final value until then. */
export function CountUp(props: { value: number; suffix?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [shown, setShown] = useState(props.value);
  useEffect(() => {
    const el = ref.current;
    if (!el || reducedMotion() || !("IntersectionObserver" in window) || props.value === 0) return;
    setShown(0);
    let frame = 0;
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return;
      io.disconnect();
      const start = performance.now();
      const tick = (now: number) => {
        const t = Math.min(1, (now - start) / 1200);
        setShown(Math.round(props.value * (1 - Math.pow(1 - t, 3))));
        if (t < 1) frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
    });
    io.observe(el);
    return () => {
      io.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [props.value]);
  return (
    <span ref={ref}>
      {shown}
      {props.suffix}
    </span>
  );
}
