import { API_URL, DEMO } from "./base";
import { DemoError, demoApi } from "./demo";
import { Lang, SERVER_ERRORS_ES } from "./i18n";

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) {
    super(message);
  }
}

type Messages = { network: string; tooMany: string; invalid: string; generic: string };

// When the site and the server are on different sites (GitHub Pages + a hosted server),
// browsers won't share the login cookie, so the server hands the page a token to send
// back in a header. It is kept only for this browser tab's session.
const TOKEN_KEY = "clyvexa.session";
function token(): string | null {
  try {
    return API_URL ? window.sessionStorage.getItem(TOKEN_KEY) : null;
  } catch {
    return null;
  }
}
function setToken(value: string | null): void {
  try {
    if (value) window.sessionStorage.setItem(TOKEN_KEY, value);
    else window.sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* blocked storage: the user just logs in again */
  }
}

/** Fetch options for the server: same-origin cookie, or the header token across sites. */
function request(method: string, headers: Record<string, string> = {}): RequestInit {
  const t = token();
  if (t) headers["authorization"] = "Bearer " + t;
  return { method, credentials: API_URL ? "omit" : "same-origin", headers };
}

/** A server URL: same origin, or the configured server for the website-only build. */
export const serverUrl = (path: string) => API_URL + path;

// Same-origin JSON calls to the FastAPI backend. Errors carry a user-facing
// message (in Spanish when the server's error code has a translation).
export async function api<T>(
  method: string,
  path: string,
  body: unknown,
  lang: Lang,
  msg: Messages,
  onLoginRequired?: () => void,
): Promise<T> {
  if (DEMO) {
    // Website-only build: replay the recorded sample session instead (see demo.ts).
    try {
      return (await demoApi(method, path, body, lang)) as T;
    } catch (e) {
      if (e instanceof DemoError) throw new ApiError(e.message, e.status, "demo");
      throw e;
    }
  }
  const init = request(method);
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    (init.headers as Record<string, string>)["content-type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let resp: Response;
  try {
    resp = await fetch(serverUrl(path), init);
  } catch {
    throw new ApiError(msg.network, 0);
  }
  if (path === "/api/auth/logout" && resp.ok) setToken(null);
  if (resp.status === 204) return null as T;
  let data: any = null;
  try {
    data = await resp.json();
  } catch {
    /* non-JSON error page */
  }
  if (!resp.ok) {
    const detail = data && data.detail;
    const code: string | undefined = detail && detail.error;
    if (resp.status === 401 && code === "login_required") setToken(null);
    if (resp.status === 401 && code === "login_required" && !path.startsWith("/api/auth/")) onLoginRequired?.();
    const translated = lang === "es" && code ? SERVER_ERRORS_ES[code] : undefined;
    const message =
      translated ??
      (detail && detail.message) ??
      (resp.status === 429 ? msg.tooMany : resp.status === 422 ? msg.invalid : msg.generic);
    throw new ApiError(message, resp.status, code);
  }
  if (data && typeof data === "object" && "session_token" in data) {
    setToken(data.session_token);
    delete data.session_token;
  }
  return data as T;
}

// For binary responses (letter PDFs).
export async function apiBlob(path: string, body: unknown): Promise<Blob> {
  if (DEMO) throw new ApiError("pdf", 400, "demo"); // no PDF service in the demo
  const resp = await fetch(serverUrl(path), { ...request("POST", { "content-type": "application/json" }), body: JSON.stringify(body) });
  if (!resp.ok) throw new ApiError("pdf", resp.status);
  return resp.blob();
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
