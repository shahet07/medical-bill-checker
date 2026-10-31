import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Medical Bill Checker",
  description: "Understand your medical bill, compare it with your insurance statement, and get a letter to send.",
  icons: {
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/favicon-32.png", sizes: "32x32", type: "image/png" },
      { url: "/favicon-48.png", sizes: "48x48", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
  },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#1f5fbf" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
