import type { Metadata } from "next";
import App from "@/components/App";
import NotHosted from "@/components/site/NotHosted";
import { STATIC_ONLY } from "@/lib/base";

export const metadata: Metadata = { title: "Check my bill · Clyvexa" };

export default function AppPage() {
  return STATIC_ONLY ? <NotHosted what="app" /> : <App />;
}
