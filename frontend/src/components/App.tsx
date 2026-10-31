"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AppProvider, useApp } from "@/lib/app";
import { ApiError, api } from "@/lib/api";
import { Lang, STRINGS } from "@/lib/i18n";
import type { CaseData, User } from "@/lib/types";
import { AccountView, AuthView } from "./AuthViews";
import { ConfirmView, FailedView, StatusView, UploadView } from "./CaseViews";
import Header from "./Header";
import Refunds from "./Refunds";
import Results from "./Results";

export type View = "auth" | "account" | "upload" | "status" | "confirm" | "failed" | "results" | "refunds";

const POLL_MS = 3000;
const CASE_KEY = "billchecker.case";
const LANG_KEY = "billchecker.lang";

function storage(kind: "local" | "session") {
  try {
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null; // blocked storage: features that remember things just won't
  }
}

export default function App() {
  const [lang, setLang] = useState<Lang>("en");
  const [view, setView] = useState<View | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [caseId, setCaseId] = useState<string | null>(null);
  const [caseData, setCaseData] = useState<CaseData | null>(null);
  const [error, setError] = useState("");
  const [registerMode, setRegisterMode] = useState(false);
  const [historyKey, setHistoryKey] = useState(0);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const switchingLanguage = useRef(false);

  const t = useCallback((key: string) => (STRINGS[lang][key] ?? STRINGS.en[key]) as string, [lang]);

  const stopPolling = () => {
    if (pollTimer.current) clearTimeout(pollTimer.current);
    pollTimer.current = null;
  };

  const remember = (id: string | null) => {
    setCaseId(id);
    const s = storage("session");
    if (!s) return;
    if (id) s.setItem(CASE_KEY, id);
    else s.removeItem(CASE_KEY);
  };

  const show = (v: View) => {
    setView(v);
    window.scrollTo(0, 0);
  };

  const showAuth = useCallback((message: string, register = false) => {
    stopPolling();
    setUser(null);
    setCaseData(null);
    remember(null);
    setRegisterMode(register);
    setError(message);
    show("auth");
  }, []);

  const onLoginRequired = useCallback(() => showAuth(t("session_expired")), [showAuth, t]);

  const call = useCallback(
    <T,>(method: string, path: string, body?: unknown) =>
      api<T>(
        method,
        path,
        body,
        lang,
        { network: t("err_network"), tooMany: t("err_429"), invalid: t("err_422"), generic: t("err_generic") },
        onLoginRequired,
      ),
    [lang, t, onLoginRequired],
  );

  const reset = (message = "") => {
    stopPolling();
    remember(null);
    setCaseData(null);
    setError(message);
    setHistoryKey((k) => k + 1);
    show("upload");
  };

  // --- Polling ---------------------------------------------------------------------------

  const poll = useCallback(
    async (id: string) => {
      stopPolling();
      let c: CaseData;
      try {
        c = await call<CaseData>("GET", "/api/cases/" + id);
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return reset(t("expired_or_deleted"));
        pollTimer.current = setTimeout(() => poll(id), POLL_MS * 2);
        return;
      }
      setCaseData(c);
      if (c.status === "ready") return show("results");
      if (c.status === "needs_confirmation") return show("confirm");
      if (c.status === "failed") return show("failed");
      setView("status");
      pollTimer.current = setTimeout(() => poll(id), POLL_MS);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [call, t],
  );

  const openCase = (id: string) => {
    remember(id);
    setCaseData(null);
    show("status");
    poll(id);
  };

  // --- Start-up --------------------------------------------------------------------------

  useEffect(() => {
    let initial: Lang = (navigator.language || "").toLowerCase().startsWith("es") ? "es" : "en";
    const saved = storage("local")?.getItem(LANG_KEY);
    if (saved === "en" || saved === "es") initial = saved;
    setLang(initial);
    api<{ user: User | null }>("GET", "/api/auth/session", undefined, initial, {
      network: "", tooMany: "", invalid: "", generic: "",
    })
      .then(({ user }) => {
        if (!user) return showAuth("");
        setUser(user);
        const resume = storage("session")?.getItem(CASE_KEY);
        if (resume) openCase(resume);
        else reset();
      })
      .catch(() => showAuth(""));
    return stopPolling;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
    storage("local")?.setItem(LANG_KEY, lang);
  }, [lang]);

  // Explanations are written in the case's language; rewrite them when the user switches.
  useEffect(() => {
    if (view !== "results" || !caseData || !caseId || caseData.language === lang || switchingLanguage.current) return;
    switchingLanguage.current = true;
    call("PUT", "/api/cases/" + caseId + "/language", { language: lang })
      .then(() => {
        show("status");
        poll(caseId);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => (switchingLanguage.current = false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang, view, caseData]);

  // --- Actions ----------------------------------------------------------------------------

  const loggedIn = (u: User) => {
    setUser(u);
    reset();
  };

  const logout = async () => {
    try {
      await call("POST", "/api/auth/logout");
    } catch {
      /* already logged out */
    }
    showAuth(t("logged_out"));
  };

  const deleteCase = async () => {
    if (!caseId) return reset();
    if (!window.confirm(t("confirm_delete"))) return;
    try {
      await call("DELETE", "/api/cases/" + caseId);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) return setError((e as Error).message);
    }
    reset(t("deleted"));
  };

  const discardAndReset = async () => {
    if (caseId) {
      try {
        await call("DELETE", "/api/cases/" + caseId);
      } catch {
        /* expired or already gone */
      }
    }
    reset();
  };

  const afterSubmit = (id: string) => {
    show("status");
    poll(id);
  };

  return (
    <AppProvider lang={lang} setError={setError} onLoginRequired={onLoginRequired}>
      <div className="app-shell">
      <Header
        user={user}
        showUserMenu={!!user && view !== "auth"}
        onAccount={() => {
          stopPolling();
          setError("");
          show("account");
        }}
        onLogout={logout}
        onRefunds={() => {
          stopPolling();
          setError("");
          show("refunds");
        }}
        onToggleLang={() => setLang(lang === "es" ? "en" : "es")}
      />
      <main className="wrap">
        <p id="error-banner" className="banner banner-error" role="alert" hidden={!error}>
          {error}
        </p>
        <AuthView hidden={view !== "auth"} registerMode={registerMode} setRegisterMode={setRegisterMode} onLoggedIn={loggedIn} />
        <AccountView
          hidden={view !== "account"}
          user={user}
          onUserChange={setUser}
          onBack={() => reset()}
          onDeleted={() => showAuth(t("account_deleted"))}
        />
        <UploadView
          hidden={view !== "upload"}
          historyKey={historyKey}
          loggedIn={!!user}
          onCreated={(id) => {
            remember(id);
            afterSubmit(id);
          }}
          onOpenCase={openCase}
        />
        <Refunds hidden={view !== "refunds"} onBack={() => reset()} />
        <StatusView hidden={view !== "status"} caseData={caseData} onCancel={deleteCase} />
        <ConfirmView hidden={view !== "confirm"} caseData={caseData} caseId={caseId} onSubmitted={afterSubmit} />
        <FailedView hidden={view !== "failed"} caseData={caseData} onRestart={discardAndReset} />
        <Results
          hidden={view !== "results"}
          caseId={caseId}
          caseData={view === "results" ? caseData : null}
          onResubmitted={afterSubmit}
          onNewBill={() => reset()}
          onDelete={deleteCase}
        />
      </main>
      <Footer />
      </div>
    </AppProvider>
  );
}

function Footer() {
  const { ts } = useApp();
  return (
    <footer className="wrap site-footer">
      <p>{ts("footer")}</p>
    </footer>
  );
}
