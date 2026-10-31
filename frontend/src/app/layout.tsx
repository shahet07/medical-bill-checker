import type { Metadata, Viewport } from "next";
import { Figtree, Fraunces } from "next/font/google";
import { at } from "@/lib/base";
import "./globals.css";
import "./site.css";
import "./app.css";

// The public address, for absolute links in social previews. Set SITE_URL when building for a real domain.
const siteUrl = process.env.SITE_URL;

export const metadata: Metadata = {
  ...(siteUrl ? { metadataBase: new URL(siteUrl) } : {}),
  title: "Clyvexa: Medical Bill Checker",
  description: "Understand your medical bill, compare it with your insurance statement, and get a letter to send.",
  icons: {
    icon: [
      { url: at("/icon.svg"), type: "image/svg+xml" },
      { url: at("/favicon-32.png"), sizes: "32x32", type: "image/png" },
      { url: at("/favicon-48.png"), sizes: "48x48", type: "image/png" },
    ],
    apple: [{ url: at("/apple-touch-icon.png"), sizes: "180x180" }],
  },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#1f5fbf" };

// Fonts are downloaded at build time and served from this site (no third-party requests).
const serif = Fraunces({ subsets: ["latin"], variable: "--font-serif", display: "swap" });
const sans = Figtree({ subsets: ["latin"], variable: "--font-sans", display: "swap" });

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={serif.variable + " " + sans.variable}>
      <body>{children}</body>
    </html>
  );
}
