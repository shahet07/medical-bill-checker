// The site's path prefix. Empty when FastAPI serves the site at the root; set
// (e.g. "/medical-bill-checker") for a GitHub Pages build, which lives under
// the repository's name. Inlined at build time.
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

/** A site-relative URL ("/privacy") with the prefix applied. */
export const at = (path: string) => BASE_PATH + path;

/** True for the website-only build (GitHub Pages), where there is no API server behind it. */
export const STATIC_ONLY = process.env.NEXT_PUBLIC_STATIC_ONLY === "1";
