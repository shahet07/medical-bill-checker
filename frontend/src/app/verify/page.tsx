import type { Metadata } from "next";
import VerifyPacket from "@/components/VerifyPacket";

export const metadata: Metadata = { title: "Verify a billing letter · Medical Bill Checker" };

export default function VerifyPage() {
  return <VerifyPacket />;
}
