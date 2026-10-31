import type { NextConfig } from "next";

// Built as static files (out/) that FastAPI serves, so the app stays one server
// with same-origin cookies. In `next dev`, API calls are proxied to FastAPI.
const api = process.env.BILLCHECKER_API ?? "http://127.0.0.1:8765";
const isDev = process.env.NODE_ENV === "development";
// Set for a GitHub Pages build, which is served under /<repository>/.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || undefined;

const config: NextConfig = {
  output: "export",
  basePath,
  // GitHub Pages serves folders, so each page becomes page/index.html there.
  trailingSlash: Boolean(basePath),
  images: { unoptimized: true },
  reactStrictMode: true,
  poweredByHeader: false,
  ...(isDev ? { async rewrites() { return [{ source: "/api/:path*", destination: `${api}/api/:path*` }]; } } : {}),
};

export default config;
