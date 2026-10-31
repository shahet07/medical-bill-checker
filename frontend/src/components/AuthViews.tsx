"use client";

import { useState } from "react";
import { useApp } from "@/lib/app";
import type { User } from "@/lib/types";

export function AuthView(props: {
  hidden: boolean;
  registerMode: boolean;
  setRegisterMode: (v: boolean) => void;
  onLoggedIn: (u: User) => void;
}) {
  const { t, ts, call, setError } = useApp();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [consent, setConsent] = useState(false);
  const [radar, setRadar] = useState(false);

  const submit = async (e: React.FormEvent, register: boolean) => {
    e.preventDefault();
    setError("");
    if (!email.trim() || !password) return setError(t("err_login_fields"));
    try {
      const user = register
        ? await call<User>("POST", "/api/auth/register", { email: email.trim(), password, research_consent: consent, radar_consent: radar })
        : await call<User>("POST", "/api/auth/login", { email: email.trim(), password });
      setPassword("");
      props.onLoggedIn(user);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const switchTo = (register: boolean) => {
    setError("");
    props.setRegisterMode(register);
  };

  return (
    <section id="auth-view" className="card narrow" hidden={props.hidden}>
      <form id="login-form" noValidate hidden={props.registerMode} onSubmit={(e) => submit(e, false)}>
        <h2>{ts("login_title")}</h2>
        <div className="field">
          <label htmlFor="login-email">{ts("email_label")}</label>
          <input id="login-email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="login-password">{ts("password_label")}</label>
          <input id="login-password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <button type="submit" className="primary">{ts("login_button")}</button>
        <p className="switch">
          <span>{ts("no_account")}</span>{" "}
          <button id="show-register" type="button" className="link" onClick={() => switchTo(true)}>
            {ts("create_account")}
          </button>
        </p>
      </form>
      <form id="register-form" noValidate hidden={!props.registerMode} onSubmit={(e) => submit(e, true)}>
        <h2>{ts("register_title")}</h2>
        <div className="field">
          <label htmlFor="reg-email">{ts("email_label")}</label>
          <input id="reg-email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="reg-password">{ts("password_label")}</label>
          <input id="reg-password" type="password" autoComplete="new-password" minLength={10} required value={password} onChange={(e) => setPassword(e.target.value)} />
          <p className="hint">{ts("password_hint")}</p>
        </div>
        <label className="consent">
          <input id="reg-consent" type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /> <span>{ts("consent_label")}</span>
        </label>
        <p className="hint">{ts("consent_detail")}</p>
        <label className="consent">
          <input id="reg-radar" type="checkbox" checked={radar} onChange={(e) => setRadar(e.target.checked)} /> <span>{t("radar_consent_label")}</span>
        </label>
        <p className="hint">{t("radar_consent_detail")}</p>
        <button type="submit" className="primary">{ts("register_button")}</button>
        <p className="switch">
          <span>{ts("have_account")}</span>{" "}
          <button id="show-login" type="button" className="link" onClick={() => switchTo(false)}>
            {ts("login_title")}
          </button>
        </p>
      </form>
    </section>
  );
}

export function AccountView(props: {
  hidden: boolean;
  user: User | null;
  onUserChange: (u: User) => void;
  onBack: () => void;
  onDeleted: () => void;
}) {
  const { t, ts, call, setError } = useApp();
  const [consent, setConsent] = useState<boolean | null>(null);
  const [consentSaved, setConsentSaved] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [passwordSaved, setPasswordSaved] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [radar, setRadar] = useState<boolean | null>(null);
  const [radarSaved, setRadarSaved] = useState(false);
  const checked = consent ?? !!props.user?.research_consent;
  const radarChecked = radar ?? !!props.user?.radar_consent;

  const saveRadar = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      props.onUserChange(await call<User>("PUT", "/api/auth/radar-consent", { radar_consent: radarChecked }));
      setRadarSaved(true);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const saveConsent = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      props.onUserChange(await call<User>("PUT", "/api/auth/consent", { research_consent: checked }));
      setConsentSaved(true);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!current || !next) return setError(t("err_new_password"));
    try {
      await call("POST", "/api/auth/password", { current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      setPasswordSaved(true);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const deleteAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!deletePassword) return setError(t("err_login_fields"));
    if (!window.confirm(t("confirm_delete_account"))) return;
    try {
      await call("DELETE", "/api/auth/account", { password: deletePassword });
      setDeletePassword("");
      props.onDeleted();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <section id="account-view" className="card narrow" hidden={props.hidden}>
      <h2>{ts("my_account")}</h2>
      <p>
        <span>{ts("signed_in_as")}</span> <strong id="account-email">{props.user?.email}</strong>
      </p>
      <form id="consent-form" className="account-block" noValidate onSubmit={saveConsent}>
        <label className="consent">
          <input id="account-consent" type="checkbox" checked={checked} onChange={(e) => { setConsent(e.target.checked); setConsentSaved(false); }} />{" "}
          <span>{ts("consent_label")}</span>
        </label>
        <p className="hint">{ts("consent_detail")}</p>
        <button type="submit" className="small">{ts("save")}</button>
        <span id="consent-saved" className="thanks" hidden={!consentSaved}> {ts("saved")}</span>
      </form>
      <form id="radar-form" className="account-block" noValidate onSubmit={saveRadar}>
        <label className="consent">
          <input id="account-radar" type="checkbox" checked={radarChecked} onChange={(e) => { setRadar(e.target.checked); setRadarSaved(false); }} />{" "}
          <span>{t("radar_consent_label")}</span>
        </label>
        <p className="hint">{t("radar_consent_detail")}</p>
        <button type="submit" className="small">{ts("save")}</button>
        <span id="radar-saved" className="thanks" hidden={!radarSaved}> {ts("saved")}</span>
      </form>
      <form id="password-form" className="account-block" noValidate onSubmit={changePassword}>
        <h3>{ts("change_password")}</h3>
        <div className="field">
          <label htmlFor="pw-current">{ts("current_password")}</label>
          <input id="pw-current" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="pw-new">{ts("new_password")}</label>
          <input id="pw-new" type="password" autoComplete="new-password" minLength={10} value={next} onChange={(e) => setNext(e.target.value)} />
          <p className="hint">{ts("password_hint")}</p>
        </div>
        <button type="submit" className="small">{ts("change_password")}</button>
        <span id="password-saved" className="thanks" hidden={!passwordSaved}> {ts("saved")}</span>
      </form>
      <form id="delete-account-form" className="account-block" noValidate onSubmit={deleteAccount}>
        <h3>{ts("delete_account")}</h3>
        <p className="hint">{ts("delete_account_detail")}</p>
        <div className="field">
          <label htmlFor="del-password">{ts("password_label")}</label>
          <input id="del-password" type="password" autoComplete="current-password" value={deletePassword} onChange={(e) => setDeletePassword(e.target.value)} />
        </div>
        <button type="submit" className="small danger">{ts("delete_account")}</button>
      </form>
      <button id="account-back" type="button" onClick={props.onBack}>{ts("back")}</button>
    </section>
  );
}
