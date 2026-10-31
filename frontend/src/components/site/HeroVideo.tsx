"use client";

import { useEffect, useRef, useState } from "react";

/** Full-bleed, muted background video for the hero, with a pause button. Stays on its poster
 * for visitors who ask for reduced motion. If the files are missing, the hero's gradient shows. */
export default function HeroVideo(props: { pauseLabel: string; playLabel: string }) {
  const video = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    const v = video.current;
    if (!v) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      v.pause();
      return;
    }
    v.play().catch(() => setPlaying(false));
  }, []);

  const toggle = () => {
    const v = video.current;
    if (!v) return;
    if (v.paused) v.play().catch(() => undefined);
    else v.pause();
  };

  return (
    <>
      <video
        ref={video}
        className="hero-video"
        muted
        loop
        playsInline
        preload="metadata"
        poster="/media/hero-poster.jpg"
        aria-hidden="true"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
      >
        <source src="/media/hero-360.mp4" type="video/mp4" media="(max-width: 700px)" />
        <source src="/media/hero-720.mp4" type="video/mp4" />
      </video>
      <div className="hero-shade" aria-hidden="true" />
      <button type="button" className="video-toggle" onClick={toggle} aria-label={playing ? props.pauseLabel : props.playLabel} aria-pressed={!playing}>
        {playing ? (
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="7" y="6" width="3.2" height="12" rx="1" />
            <rect x="13.8" y="6" width="3.2" height="12" rx="1" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M8 6.5v11l9-5.5z" />
          </svg>
        )}
      </button>
    </>
  );
}
