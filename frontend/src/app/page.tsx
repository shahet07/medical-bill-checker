import type { Metadata } from "next";
import Landing from "@/components/site/Landing";

export const metadata: Metadata = {
  title: "Clyvexa: find the mistakes in your medical bill",
  description:
    "Upload your medical bill and your insurer's Explanation of Benefits. Clyvexa compares them line by line, explains what it finds in plain language, and writes the letter to send.",
  openGraph: {
    title: "Clyvexa: find the mistakes in your medical bill",
    description: "Compare your bill with your insurance statement, understand it, and get a letter to send.",
    ...(process.env.SITE_URL ? { images: ["/og.png"] } : {}),
  },
};

export default function Home() {
  return <Landing />;
}
