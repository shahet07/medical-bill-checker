import type { Metadata } from "next";
import VerifyPacket from "@/components/VerifyPacket";
import NotHosted from "@/components/site/NotHosted";
import { STATIC_ONLY } from "@/lib/base";

export const metadata: Metadata = { title: "Verify a billing letter · Clyvexa" };

export default function VerifyPage() {
  return STATIC_ONLY ? <NotHosted what="verify" /> : <VerifyPacket />;
}
