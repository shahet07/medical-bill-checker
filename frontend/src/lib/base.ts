// The site's path prefix. Empty when FastAPI serves the site at the root; set
// (e.g. "/medical-bill-checker") for a GitHub Pages build, which lives under
// the repository's name. Inlined at build time.
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

/** A site-relative URL ("/privacy") with the prefix applied. */
export const at = (path: string) => BASE_PATH + path;

/** True for the website-only build (GitHub Pages), which FastAPI does not serve. */
export const STATIC_ONLY = process.env.NEXT_PUBLIC_STATIC_ONLY === "1";

/** The Clyvexa server the website-only build talks to (e.g. "https://clyvexa.onrender.com").
 * Empty: same origin (FastAPI serves this site), or no server at all on a static build. */
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/+$/, "");

/** A static build with no server: the app runs as a demo on a recorded sample (lib/demo.ts). */
export const DEMO = STATIC_ONLY && !API_URL;
