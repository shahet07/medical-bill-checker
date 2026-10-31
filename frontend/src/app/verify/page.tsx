import type { Metadata } from "next";
import VerifyPacket from "@/components/VerifyPacket";
import NotHosted from "@/components/site/NotHosted";
import { DEMO } from "@/lib/base";

export const metadata: Metadata = { title: "Verify a billing letter · Clyvexa" };

export default function VerifyPage() {
  return DEMO ? <NotHosted /> : <VerifyPacket />;
}
