"use client";

import { useApp } from "@/lib/app";
import { STATIC_ONLY, at } from "@/lib/base";
import type { User } from "@/lib/types";

const DEMO_BADGE = { en: "Demo · sample bill", es: "Demostración · factura de muestra" };

export default function Header(props: {
  user: User | null;
  showUserMenu: boolean;
  onAccount: () => void;
  onLogout: () => void;
  onRefunds: () => void;
  onToggleLang: () => void;
}) {
  const { lang, t, ts } = useApp();
  return (
    <header className="site-header app-top">
      <div className="app-top-glow" aria-hidden="true" />
      <div className="wrap wide">
        <div className="header-row">
          <h1>
            <a href={at("/")} className="brand home-link">
              <img src={at("/icon.svg")} alt="" width={40} height={40} className="brand-mark" />
              <span className="app-brand-name">
                {ts("app_title")}
                <small>{lang === "es" ? "Revisión de facturas médicas" : "Medical bill checker"}</small>
              </span>
            </a>
          </h1>
          <div className="header-actions">
            {STATIC_ONLY && <span className="demo-badge">{DEMO_BADGE[lang]}</span>}
            <span id="user-menu" hidden={!props.showUserMenu}>
              <span id="user-email" className="muted">
                {props.user?.email}
              </span>
              <button id="refunds-button" type="button" className="small" onClick={props.onRefunds}>
                {t("refunds_button")}
              </button>
              <button id="account-button" type="button" className="small" onClick={props.onAccount}>
                {ts("my_account")}
              </button>
              <button id="logout-button" type="button" className="small" onClick={props.onLogout}>
                {ts("log_out")}
              </button>
            </span>
            <button id="lang-toggle" type="button" className="small" lang={lang === "es" ? "en" : "es"} onClick={props.onToggleLang}>
              {t("lang_toggle")}
            </button>
          </div>
        </div>
        <p className="tagline">{ts("tagline")}</p>
      </div>
    </header>
  );
}
