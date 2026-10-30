"use client";

import { createContext, useCallback, useContext, useMemo } from "react";
import { api } from "./api";
import { Lang, STATIC_EN, STATIC_ES, STRINGS } from "./i18n";

export interface AppContextValue {
  lang: Lang;
  /** Messages built in code, with {placeholders}. */
  t: (key: string, vars?: Record<string, string | number>) => string;
  /** Lists of messages (e.g. example questions). */
  tl: (key: string) => string[];
  /** Page text (labels, headings). */
  ts: (key: string) => string;
  call: <T>(method: string, path: string, body?: unknown) => Promise<T>;
  setError: (message: string) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp outside AppProvider");
  return ctx;
}

export function AppProvider(props: {
  lang: Lang;
  setError: (m: string) => void;
  onLoginRequired: () => void;
  children: React.ReactNode;
}) {
  const { lang, setError, onLoginRequired } = props;

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>) => {
      let text = (STRINGS[lang][key] ?? STRINGS.en[key] ?? key) as string;
      for (const [k, v] of Object.entries(vars ?? {})) text = text.replace("{" + k + "}", String(v));
      return text;
    },
    [lang],
  );
  const tl = useCallback((key: string) => (STRINGS[lang][key] ?? STRINGS.en[key] ?? []) as string[], [lang]);
  const ts = useCallback((key: string) => (lang === "es" ? STATIC_ES[key] : undefined) ?? STATIC_EN[key] ?? key, [lang]);
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

  const value = useMemo(() => ({ lang, t, tl, ts, call, setError }), [lang, t, tl, ts, call, setError]);
  return <AppContext.Provider value={value}>{props.children}</AppContext.Provider>;
}
