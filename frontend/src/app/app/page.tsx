import type { Metadata } from "next";
import App from "@/components/App";

export const metadata: Metadata = { title: "Check my bill · Clyvexa" };

// On the website-only build (GitHub Pages) the app runs in demo mode (see lib/demo.ts).
export default function AppPage() {
  return <App />;
}
