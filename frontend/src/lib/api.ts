import { STATIC_ONLY } from "./base";
import { DemoError, demoApi } from "./demo";
import { Lang, SERVER_ERRORS_ES } from "./i18n";

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) {
    super(message);
  }
}

type Messages = { network: string; tooMany: string; invalid: string; generic: string };

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
  if (STATIC_ONLY) {
    // Website-only build: replay the recorded sample session instead (see demo.ts).
    try {
      return (await demoApi(method, path, body, lang)) as T;
    } catch (e) {
      if (e instanceof DemoError) throw new ApiError(e.message, e.status, "demo");
      throw e;
    }
  }
  const init: RequestInit = { method, credentials: "same-origin", headers: {} };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    (init.headers as Record<string, string>)["content-type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let resp: Response;
  try {
    resp = await fetch(path, init);
  } catch {
    throw new ApiError(msg.network, 0);
  }
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
    if (resp.status === 401 && code === "login_required" && !path.startsWith("/api/auth/")) onLoginRequired?.();
    const translated = lang === "es" && code ? SERVER_ERRORS_ES[code] : undefined;
    const message =
      translated ??
      (detail && detail.message) ??
      (resp.status === 429 ? msg.tooMany : resp.status === 422 ? msg.invalid : msg.generic);
    throw new ApiError(message, resp.status, code);
  }
  return data as T;
}

// For binary responses (letter PDFs).
export async function apiBlob(path: string, body: unknown): Promise<Blob> {
  if (STATIC_ONLY) throw new ApiError("pdf", 400, "demo"); // no PDF service in the demo
  const resp = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
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
