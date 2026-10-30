import { Lang, STRINGS } from "./i18n";

// "1250.5" -> "$1,250.50". Works on the decimal string, never a float.
export function money(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const s = String(value);
  const neg = s.startsWith("-");
  const [whole, frac = ""] = s.replace("-", "").split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (neg ? "−" : "") + "$" + grouped + "." + (frac + "00").slice(0, 2);
}

export function shortDate(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  const month = (STRINGS[lang].months as string[])[m - 1];
  return lang === "es" ? `${d} ${month} ${y}` : `${month} ${d}, ${y}`;
}

// "1250", "$1,250.00", "-40" -> decimal string; "" -> null; otherwise throws.
export function parseAmount(raw: string, message: string): string | null {
  const s = raw.trim().replace(/[$,\s]/g, "");
  if (!s) return null;
  if (!/^-?\d+(\.\d{1,2})?$/.test(s)) throw new Error(message);
  return s;
}
