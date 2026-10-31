"use client";

import { useState } from "react";
import { useApp } from "@/lib/app";
import type { RadarPattern } from "@/lib/types";

function PatternList({ patterns }: { patterns: RadarPattern[] }) {
  const { t } = useApp();
  return (
    <ul className="radar-list">
      {patterns.map((p, i) => (
        <li key={i}>
          <strong>{t("rule_" + p.rule)}</strong>
          {p.code ? <span className="muted"> · {t("radar_code", { code: p.code })}</span> : null}
          <span className="radar-meta">
            {t("radar_reports", { n: p.reports })}
            {p.confirmed ? " · " + t("radar_confirmed_" + p.confirmed) : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

// Patterns other patients reported at this bill's provider (shown only past the k threshold).
export function RadarCard({ provider, patterns }: { provider: string; patterns: RadarPattern[] }) {
  const { t } = useApp();
  if (!patterns.length) return null;
  return (
    <div className="card radar" id="radar-card">
      <h2>{t("radar_title")}</h2>
      <p className="muted">{t("radar_intro", { provider })}</p>
      <PatternList patterns={patterns} />
    </div>
  );
}

export function RadarSearch() {
  const { t, call, setError } = useApp();
  const [q, setQ] = useState("");
  const [result, setResult] = useState<{ k: number; providers: { provider_name: string; patterns: RadarPattern[] }[] } | null>(null);

  const search = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      setResult(await call("GET", "/api/radar?q=" + encodeURIComponent(q.trim())));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div id="radar-search" className="radar-search">
      <h2>{t("radar_search_title")}</h2>
      <p className="muted">{t("radar_search_intro")}</p>
      <form id="radar-form-search" className="inline-form" noValidate onSubmit={search}>
        <label htmlFor="radar-q" className="sr-only">{t("radar_search_label")}</label>
        <input id="radar-q" type="text" placeholder={t("radar_search_label")} maxLength={200} value={q} onChange={(e) => setQ(e.target.value)} />
        <button type="submit">{t("radar_search_button")}</button>
      </form>
      {result ? (
        result.providers.length ? (
          <div id="radar-results">
            {result.providers.map((p) => (
              <div key={p.provider_name} className="radar-provider">
                <h3>{p.provider_name}</h3>
                <PatternList patterns={p.patterns} />
              </div>
            ))}
          </div>
        ) : (
          <p id="radar-results" className="muted">{t("radar_none", { k: result.k })}</p>
        )
      ) : null}
    </div>
  );
}
