// Demo mode for the website-only build (GitHub Pages), which has no server.
// Answers the app's API calls from a real session recorded on a synthetic
// sample bill (scripts/capture_demo.py), with short delays so the app behaves
// as it does live. Nothing the visitor enters leaves the browser.
import { at } from "./base";
import type { Lang } from "./i18n";
import { STRINGS } from "./i18n";
import recording from "./demo-recording.json";

interface Recorded {
  method: string;
  path: string;
  query: string;
  status: number;
  request: any;
  response: any;
}

const CALLS = recording as Recorded[];
const CASE_ID = "demo-case";
const CHECK_MS = 5200; // how long the sample "takes" to check
const REREAD_MS = 1800; // re-explaining in another language

const DEMO_ONLY: Record<Lang, string> = {
  en: "That isn't available in the demo. Run the full app to use it.",
  es: "Eso no está disponible en la demostración. Use la aplicación completa para hacerlo.",
};
const CALL_END: Record<Lang, string> = {
  en: "(Demo) In the full app the representative keeps answering what you say. Ask for feedback to see how the call went.",
  es: "(Demostración) En la aplicación completa, el representante sigue respondiendo a lo que usted dice. Pida comentarios para ver cómo le fue.",
};
const ASK_OTHER: Record<Lang, string> = {
  en: "In the demo, answers are ready for the example questions above. The full app answers any question about your bill.",
  es: "En la demostración hay respuestas para las preguntas de ejemplo. La aplicación completa responde cualquier pregunta sobre su factura.",
};

/** The message for features the demo can't do (e.g. PDFs). */
export const demoOnly = (lang: Lang) => DEMO_ONLY[lang];

export class DemoError extends Error {
  constructor(message: string, readonly status = 400) {
    super(message);
  }
}

const state = {
  loggedIn: true,
  created: 0 as number, // when the sample was submitted (0 = no case yet)
  rereadAt: 0,
  language: "en" as Lang,
};

const pick = (method: string, path: string, test: (c: Recorded) => boolean = () => true) =>
  CALLS.find((c) => c.method === method && c.path === path && test(c));
const copy = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const user = () => copy(pick("POST", "/api/auth/register")!.response);
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

function caseNow(): any {
  const now = Date.now();
  const checking = now - state.created < CHECK_MS || now - state.rereadAt < REREAD_MS;
  if (checking) return { ...copy(pick("GET", "/api/cases/" + CASE_ID, (c) => c.response.status !== "ready")!.response), language: state.language };
  const ready = pick("GET", "/api/cases/" + CASE_ID, (c) => c.response.status === "ready" && c.response.language === state.language);
  return copy((ready ?? pick("GET", "/api/cases/" + CASE_ID, (c) => c.response.status === "ready"))!.response);
}

/** Replays the recorded response for an API call. */
export async function demoApi(method: string, path: string, body: unknown, lang: Lang): Promise<any> {
  await wait(250 + Math.random() * 250);
  const route = path.split("?")[0];
  const caseRoute = route.startsWith("/api/cases/" + CASE_ID);
  const json = (body && !(body instanceof FormData) ? body : {}) as any;

  switch (method + " " + route) {
    case "GET /api/auth/session":
      return { user: state.loggedIn ? user() : null };
    case "POST /api/auth/login":
    case "POST /api/auth/register":
      state.loggedIn = true;
      return user();
    case "POST /api/auth/logout":
      state.loggedIn = false;
      return null;
    case "GET /api/auth/me":
      return user();
    case "PUT /api/auth/consent":
      return { ...user(), research_consent: !!json.research_consent };
    case "PUT /api/auth/radar-consent":
      return { ...user(), radar_consent: !!json.radar_consent };
    case "GET /api/cases":
      return { cases: [] };
    case "POST /api/uploads": {
      const kind = body instanceof FormData ? body.get("kind") : "bill";
      await wait(500);
      return copy(pick("POST", "/api/uploads", (c) => c.response.kind === kind)!.response);
    }
    case "POST /api/cases":
      state.created = Date.now();
      state.language = (json.language as Lang) ?? lang;
      return copy(pick("POST", "/api/cases")!.response);
    case "GET /api/refunds":
      return copy(pick("GET", "/api/refunds")!.response);
    case "GET /api/radar":
      return { k: 10, providers: [] };
    case "POST /api/ask": {
      const asked = String(json.question ?? "").trim();
      const index = [...(STRINGS.en.ask_examples as string[]), ...(STRINGS.es.ask_examples as string[])].indexOf(asked) % 3;
      const asks = CALLS.filter((c) => c.path === "/api/ask");
      if (index >= 0 && asks[index]) {
        await wait(900);
        return copy(asks[index].response);
      }
      return { answer: ASK_OTHER[lang], fallback: true, sources: [], related: [] };
    }
  }

  if (caseRoute) {
    const rest = route.slice(("/api/cases/" + CASE_ID).length);
    if (method === "GET" && rest === "") return caseNow();
    if (method === "DELETE" && rest === "") {
      state.created = 0;
      return null;
    }
    if (method === "PUT" && rest === "/language") {
      state.language = json.language === "es" ? "es" : "en";
      state.rereadAt = Date.now();
      return { ...caseNow(), status: "queued" };
    }
    if (method === "POST" && rest === "/letter") {
      const rec = pick("POST", route, (c) => c.request?.kind === json.kind);
      if (!rec) throw new DemoError(DEMO_ONLY[lang]);
      await wait(700);
      const letter = copy(rec.response);
      const name = String(json.patient?.name ?? "").trim();
      if (name) letter.text = letter.text.split("Sam Example").join(name);
      // The recording's verification link points at the machine it was made on; use this site's page.
      const verify = window.location.origin + at("/verify/");
      letter.text = letter.text.replace(/https?:\/\/[^\s/]+\/verify\?id=\S+/g, verify);
      if (letter.verify_url) letter.verify_url = verify;
      return letter;
    }
    if (method === "POST" && rest === "/rehearse") {
      const turns = (json.turns ?? []).length;
      const recs = CALLS.filter((c) => c.path === route);
      await wait(900);
      if (turns === 0) return copy(recs[0].response);
      if (turns <= 2) return copy(recs[1].response);
      return { reply: CALL_END[lang], call_ended: true, fallback: true };
    }
    if (method === "POST" && rest === "/rehearse/score") {
      await wait(900);
      return copy(pick("POST", route)!.response);
    }
    if (method === "POST" && (rest === "/feedback" || rest === "/survey")) return null;
  }
  throw new DemoError(DEMO_ONLY[lang]);
}
