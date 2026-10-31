"use client";

import { useEffect, useState } from "react";
import type { Lang } from "@/lib/i18n";
import { SITE_TEXT, SiteText } from "@/lib/siteText";
import { at } from "@/lib/base";

const LANG_KEY = "billchecker.lang"; // shared with the app, so the choice carries over
export const SOURCE_URL = "https://github.com/shahet07/medical-bill-checker";

/** The visitor's language: saved choice, else the browser's. English on the first (static) render. */
export function useSiteLang(): [Lang, (l: Lang) => void] {
  const [lang, setLang] = useState<Lang>("en");
  useEffect(() => {
    let initial: Lang = (navigator.language || "").toLowerCase().startsWith("es") ? "es" : "en";
    try {
      const saved = window.localStorage.getItem(LANG_KEY);
      if (saved === "en" || saved === "es") initial = saved;
    } catch {}
    setLang(initial);
  }, []);
  const choose = (l: Lang) => {
    setLang(l);
    try {
      window.localStorage.setItem(LANG_KEY, l);
    } catch {}
  };
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  return [lang, choose];
}

export function SiteHeader(props: { text: SiteText; lang?: Lang; onToggleLang?: () => void; sections?: boolean }) {
  const { text, sections } = props;
  const anchor = (id: string) => (sections ? "#" + id : at("/#" + id));
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return (
    <header className={"site-nav" + (scrolled ? " scrolled" : "") + (sections ? " overlay" : "")}>
      <div className="site-wrap site-nav-row">
        <a href={at("/")} className="brand site-brand" aria-label="Clyvexa home">
          <img src={at("/icon.svg")} alt="" width={36} height={36} className="brand-mark" />
          <span className="brand-name">
            Clyvexa<small>{text.hero.eyebrow}</small>
          </span>
        </a>
        <nav aria-label="Main" className="site-links">
          <a href={anchor("how")}>{text.nav.how}</a>
          <a href={anchor("features")}>{text.nav.features}</a>
          <a href={anchor("privacy")}>{text.nav.privacy}</a>
          <a href={anchor("faq")}>{text.nav.faq}</a>
        </nav>
        <div className="site-nav-actions">
          {props.onToggleLang && (
            <button type="button" className="lang-btn" lang={props.lang === "es" ? "en" : "es"} onClick={props.onToggleLang}>
              {text.langToggle}
            </button>
          )}
          <a href={at("/app")} className="pill-btn solid">
            {text.nav.open}
          </a>
        </div>
      </div>
    </header>
  );
}

export function SiteFooter(props: { text: SiteText }) {
  const f = props.text.footer;
  const n = props.text.nav;
  return (
    <footer className="site-foot">
      <div className="site-wrap">
        <div className="site-foot-row">
          <div className="site-foot-brand">
            <a href={at("/")} className="brand site-brand">
              <img src={at("/icon.svg")} alt="" width={36} height={36} className="brand-mark" />
              <span>Clyvexa</span>
            </a>
            <p>{f.tagline}</p>
          </div>
          <nav aria-label={f.product} className="site-foot-col">
            <h2>{f.product}</h2>
            <a href={at("/app")}>{n.open}</a>
            <a href={at("/#how")}>{n.how}</a>
            <a href={at("/#features")}>{n.features}</a>
            <a href={at("/#faq")}>{n.faq}</a>
          </nav>
          <nav aria-label={f.trust} className="site-foot-col">
            <h2>{f.trust}</h2>
            <a href={at("/privacy")}>{f.privacy}</a>
            <a href={at("/terms")}>{f.terms}</a>
            <a href={at("/delete-account")}>{f.deletion}</a>
            <a href={at("/verify")}>{f.verify}</a>
          </nav>
          <nav aria-label={f.openSource} className="site-foot-col">
            <h2>{f.openSource}</h2>
            <a href={SOURCE_URL} rel="noopener">
              {f.source}
            </a>
            <a href={SOURCE_URL + "/blob/main/LICENSE"} rel="noopener">
              {f.license}
            </a>
          </nav>
        </div>
        <p className="site-disclaimer">{f.disclaimer}</p>
      </div>
    </footer>
  );
}

/** Header and footer for pages that are in English only (policies). */
export function PlainChrome(props: { children: React.ReactNode }) {
  const text = SITE_TEXT.en;
  return (
    <>
      <SiteHeader text={text} />
      {props.children}
      <SiteFooter text={text} />
    </>
  );
}
