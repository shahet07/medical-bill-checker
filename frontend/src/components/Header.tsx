"use client";

import { useApp } from "@/lib/app";
import type { User } from "@/lib/types";

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
    <header className="site-header">
      <div className="wrap">
        <div className="header-row">
          <h1>{ts("app_title")}</h1>
          <div className="header-actions">
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
