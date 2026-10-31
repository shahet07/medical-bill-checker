"use client";

import { SITE_TEXT } from "@/lib/siteText";
import HeroScan from "./HeroScan";
import Icon from "./Icon";
import { CountUp, useReveal } from "./motion";
import { SiteFooter, SiteHeader, useSiteLang } from "./SiteChrome";

// Icons in the same order as the text lists in siteText.ts.
const STEP_ICONS = ["upload", "eye", "send"];
const CHECK_ICONS = ["duplicate", "mismatch", "denied", "network", "missing", "payment", "unbundled", "itemized"];
const FEATURE_ICONS = ["letter", "phone", "refund", "radar", "ask", "words"];
const PRIVACY_ICONS = ["lock", "clock", "trash", "user", "device"];

export default function Landing() {
  const [lang, setLang] = useSiteLang();
  const s = SITE_TEXT[lang];
  useReveal();
  const [before, highlight, after] = s.hero.titleParts;
  return (
    <div className="site">
      <SiteHeader text={s} lang={lang} onToggleLang={() => setLang(lang === "es" ? "en" : "es")} sections />
      <main>
        <section className="site-hero">
          <div className="aurora" aria-hidden="true">
            <i />
            <i />
            <i />
          </div>
          <div className="site-wrap hero-grid">
            <div className="hero-copy">
              <h1>
                {before}
                <span className="hl">
                  {highlight}
                  <svg viewBox="0 0 200 16" preserveAspectRatio="none" aria-hidden="true">
                    <path d="M3 11C40 4 120 3 197 8" />
                  </svg>
                </span>
                {after}
              </h1>
              <p className="lead">{s.hero.lead}</p>
              <div className="hero-actions">
                <a href="/app" className="button primary large shine">
                  {s.hero.cta}
                  <span aria-hidden="true" className="arrow">
                    →
                  </span>
                </a>
                <a href="#how" className="button large ghost">
                  {s.hero.secondary}
                </a>
              </div>
              <ul className="hero-points">
                {s.hero.points.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </div>
            <HeroScan s={s} />
          </div>
        </section>

        <section className="stats-band" aria-label="Clyvexa in numbers">
          <ul className="site-wrap stats reveal stagger">
            {s.stats.map((st) => (
              <li key={st.label}>
                <strong>
                  <CountUp value={st.value} suffix={st.suffix} />
                </strong>
                <span>{st.label}</span>
              </li>
            ))}
          </ul>
        </section>

        <section id="how" className="site-section">
          <div className="site-wrap">
            <h2 className="reveal">{s.how.title}</h2>
            <ol className="steps reveal stagger">
              {s.how.steps.map((step, i) => (
                <li key={step.title}>
                  <span className="step-num" aria-hidden="true">
                    <Icon name={STEP_ICONS[i]} />
                    <b>{i + 1}</b>
                  </span>
                  <h3>{step.title}</h3>
                  <p>{step.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="checks" className="site-section alt">
          <div className="site-wrap">
            <h2 className="reveal">{s.checks.title}</h2>
            <p className="section-lead reveal">{s.checks.lead}</p>
            <ul className="tiles reveal stagger">
              {s.checks.items.map((c, i) => (
                <li key={c.title}>
                  <span className="tile-icon warn">
                    <Icon name={CHECK_ICONS[i]} />
                  </span>
                  <h3>{c.title}</h3>
                  <p>{c.body}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section id="features" className="site-section">
          <div className="site-wrap">
            <h2 className="reveal">{s.features.title}</h2>
            <ul className="tiles three reveal stagger">
              {s.features.items.map((c, i) => (
                <li key={c.title}>
                  <span className="tile-icon">
                    <Icon name={FEATURE_ICONS[i]} />
                  </span>
                  <h3>{c.title}</h3>
                  <p>{c.body}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section id="privacy" className="site-section alt">
          <div className="site-wrap privacy-grid">
            <div className="reveal">
              <svg className="padlock" viewBox="0 0 64 64" aria-hidden="true">
                <path className="shackle" d="M20 30V20a12 12 0 0 1 24 0v10" />
                <rect x="12" y="28" width="40" height="30" rx="7" />
                <circle cx="32" cy="41" r="4" />
                <path d="M32 45v5" />
              </svg>
              <h2>{s.privacy.title}</h2>
              <p className="section-lead">{s.privacy.lead}</p>
              <a href="/privacy" className="text-link">
                {s.privacy.link} <span aria-hidden="true">→</span>
              </a>
            </div>
            <ul className="checklist reveal stagger">
              {s.privacy.items.map((p, i) => (
                <li key={p}>
                  <span className="tile-icon ok">
                    <Icon name={PRIVACY_ICONS[i]} />
                  </span>
                  <span>{p}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section id="faq" className="site-section">
          <div className="site-wrap narrow">
            <h2 className="reveal">{s.faq.title}</h2>
            <div className="reveal stagger">
              {s.faq.items.map((item) => (
                <details key={item.q} className="faq">
                  <summary>
                    {item.q}
                    <Icon name="chevron" className="chev" />
                  </summary>
                  <p>{item.a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section className="site-cta">
          <div className="site-wrap reveal">
            <img src="/icon.svg" alt="" width={64} height={64} className="cta-mark" />
            <h2>{s.cta.title}</h2>
            <p>{s.cta.body}</p>
            <a href="/app" className="button large light shine">
              {s.cta.button}
              <span aria-hidden="true" className="arrow">
                →
              </span>
            </a>
          </div>
        </section>
      </main>
      <SiteFooter text={s} />
    </div>
  );
}
