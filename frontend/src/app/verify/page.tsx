import type { Metadata } from "next";
import VerifyPacket from "@/components/VerifyPacket";

export const metadata: Metadata = { title: "Verify a billing letter · Clyvexa" };

export default function VerifyPage() {
  return <VerifyPacket />;
}
