"use client";

import { SITE_TEXT } from "@/lib/siteText";
import Bento from "./Bento";
import HeroScan from "./HeroScan";
import Journey from "./Journey";
import Icon from "./Icon";
import { CountUp, useReveal } from "./motion";
import { SiteFooter, SiteHeader, useSiteLang } from "./SiteChrome";

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
        {/* Hero: deep blue, serif headline, the bill being checked */}
        <section className="hero dark">
          <div className="aurora" aria-hidden="true">
            <i />
            <i />
            <i />
          </div>
          <div className="site-wrap hero-grid">
            <div className="hero-copy">
              <p className="kicker">{s.hero.eyebrow}</p>
              <h1 className="display">
                {before}
                <em className="hl">
                  {highlight}
                  <svg viewBox="0 0 200 16" preserveAspectRatio="none" aria-hidden="true">
                    <path d="M3 11C40 4 120 3 197 8" />
                  </svg>
                </em>
                {after}
              </h1>
              <p className="lead">{s.hero.lead}</p>
              <div className="hero-actions">
                <a href="/app" className="pill-btn light">
                  {s.hero.cta} <span className="arrow-dot" aria-hidden="true">→</span>
                </a>
                <a href="#how" className="pill-btn outline">
                  {s.hero.secondary}
                </a>
              </div>
              <ul className="glass-pills">
                {s.hero.points.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </div>
            <HeroScan s={s} />
          </div>
        </section>

        {/* Meet + feature bento */}
        <section id="features" className="section tint">
          <div className="site-wrap">
            <div className="center-head reveal">
              <h2 className="display">{s.meet.title}</h2>
              <p className="lead">{s.meet.lead}</p>
              <a href="#how" className="circle-link">
                {s.meet.link} <span aria-hidden="true">→</span>
              </a>
            </div>
            <Bento s={s} />
          </div>
        </section>

        {/* How it works: one bill's journey through an isometric town */}
        <section id="how" className="section journey-section">
          <div className="site-wrap">
            <h2 className="sr-only">{s.journey.title}</h2>
            <div className="reveal">
              <Journey s={s} />
            </div>
          </div>
        </section>

        {/* What it checks: numbered list */}
        <section id="checks" className="section">
          <div className="site-wrap checks-grid">
            <div className="reveal sticky-head">
              <h2 className="display">{s.checks.title}</h2>
              <p className="lead">{s.checks.lead}</p>
            </div>
            <ol className="check-list reveal stagger">
              {s.checks.items.map((c, i) => (
                <li key={c.title}>
                  <span className="check-num">{String(i + 1).padStart(2, "0")}</span>
                  <div>
                    <h3>{c.title}</h3>
                    <p>{c.body}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Mission statement and numbers */}
        <section className="section dark band">
          <div className="site-wrap band-grid">
            <div className="reveal">
              <span className="band-mark">
                <img src="/icon.svg" alt="" width={52} height={52} />
              </span>
              <p className="band-label">{s.mission.label}</p>
              <blockquote className="display quote">{s.mission.quote}</blockquote>
              <p className="band-body">{s.mission.body}</p>
            </div>
            <ul className="stat-cards reveal stagger">
              {s.stats.map((st) => (
                <li key={st.label}>
                  <strong className="display">
                    <CountUp value={st.value} suffix={st.suffix} />
                  </strong>
                  <span>{st.label}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Privacy */}
        <section id="privacy" className="section tint">
          <div className="site-wrap privacy-grid">
            <div className="reveal">
              <svg className="padlock" viewBox="0 0 64 64" aria-hidden="true">
                <path className="shackle" d="M20 30V20a12 12 0 0 1 24 0v10" />
                <rect x="12" y="28" width="40" height="30" rx="7" />
                <circle cx="32" cy="41" r="4" />
                <path d="M32 45v5" />
              </svg>
              <h2 className="display">{s.privacy.title}</h2>
              <p className="lead">{s.privacy.lead}</p>
              <a href="/privacy" className="circle-link">
                {s.privacy.link} <span aria-hidden="true">→</span>
              </a>
            </div>
            <ul className="assure reveal stagger">
              {s.privacy.items.map((p, i) => (
                <li key={p}>
                  <span className="assure-icon">
                    <Icon name={PRIVACY_ICONS[i]} />
                  </span>
                  <span>{p}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* FAQ */}
        <section id="faq" className="section">
          <div className="site-wrap narrow">
            <h2 className="display reveal">{s.faq.title}</h2>
            <div className="reveal stagger">
              {s.faq.items.map((item) => (
                <details key={item.q} className="faq">
                  <summary>
                    {item.q}
                    <span className="faq-toggle" aria-hidden="true">
                      <Icon name="chevron" className="chev" />
                    </span>
                  </summary>
                  <p>{item.a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        {/* Closing call to action with floating findings */}
        <section className="section dark finale">
          <div className="floats" aria-hidden="true">
            {s.cta.floats.map(([a, b], i) => (
              <div className={"float f" + i} key={a}>
                <span className="dot" />
                <span>{a}</span>
                <em>{b}</em>
              </div>
            ))}
          </div>
          <div className="site-wrap finale-inner reveal">
            <h2 className="display">{s.cta.title}</h2>
            <p className="lead">{s.cta.body}</p>
            <a href="/app" className="pill-btn light big">
              {s.cta.button} <span className="arrow-dot" aria-hidden="true">→</span>
            </a>
            <ul className="glass-pills center">
              {s.cta.pills.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </div>
        </section>
      </main>
      <SiteFooter text={s} />
    </div>
  );
}
