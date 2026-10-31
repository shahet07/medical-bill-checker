"use client";

import { SITE_TEXT } from "@/lib/siteText";
import { SiteFooter, SiteHeader, useSiteLang } from "./SiteChrome";

export default function Landing() {
  const [lang, setLang] = useSiteLang();
  const s = SITE_TEXT[lang];
  return (
    <div className="site">
      <SiteHeader text={s} lang={lang} onToggleLang={() => setLang(lang === "es" ? "en" : "es")} sections />
      <main>
        <section className="site-hero">
          <div className="site-wrap hero-grid">
            <div>
              <p className="eyebrow">{s.hero.eyebrow}</p>
              <h1>{s.hero.title}</h1>
              <p className="lead">{s.hero.lead}</p>
              <div className="hero-actions">
                <a href="/app" className="button primary large">
                  {s.hero.cta}
                </a>
                <a href="#how" className="button large">
                  {s.hero.secondary}
                </a>
              </div>
              <ul className="hero-points">
                {s.hero.points.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </div>
            <figure className="mock" aria-label={s.mock.label}>
              <figcaption className="mock-label">{s.mock.label}</figcaption>
              <h2>{s.mock.title}</h2>
              {s.mock.flags.map((f) => (
                <div className="mock-flag" key={f.title}>
                  <strong>{f.title}</strong>
                  <span>{f.detail}</span>
                </div>
              ))}
              <p className="mock-owed">{s.mock.owed}</p>
              <span className="button primary small-fake" aria-hidden="true">
                {s.mock.letter}
              </span>
            </figure>
          </div>
        </section>

        <section id="how" className="site-section">
          <div className="site-wrap">
            <h2>{s.how.title}</h2>
            <ol className="steps">
              {s.how.steps.map((step, i) => (
                <li key={step.title}>
                  <span className="step-num" aria-hidden="true">
                    {i + 1}
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
            <h2>{s.checks.title}</h2>
            <p className="section-lead">{s.checks.lead}</p>
            <ul className="tiles">
              {s.checks.items.map((c) => (
                <li key={c.title}>
                  <h3>{c.title}</h3>
                  <p>{c.body}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section id="features" className="site-section">
          <div className="site-wrap">
            <h2>{s.features.title}</h2>
            <ul className="tiles three">
              {s.features.items.map((c) => (
                <li key={c.title}>
                  <h3>{c.title}</h3>
                  <p>{c.body}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section id="privacy" className="site-section alt">
          <div className="site-wrap privacy-grid">
            <div>
              <h2>{s.privacy.title}</h2>
              <p className="section-lead">{s.privacy.lead}</p>
              <a href="/privacy">{s.privacy.link}</a>
            </div>
            <ul className="checklist">
              {s.privacy.items.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </div>
        </section>

        <section id="faq" className="site-section">
          <div className="site-wrap narrow">
            <h2>{s.faq.title}</h2>
            {s.faq.items.map((item) => (
              <details key={item.q} className="faq">
                <summary>{item.q}</summary>
                <p>{item.a}</p>
              </details>
            ))}
          </div>
        </section>

        <section className="site-cta">
          <div className="site-wrap">
            <h2>{s.cta.title}</h2>
            <p>{s.cta.body}</p>
            <a href="/app" className="button primary large">
              {s.cta.button}
            </a>
          </div>
        </section>
      </main>
      <SiteFooter text={s} />
    </div>
  );
}
