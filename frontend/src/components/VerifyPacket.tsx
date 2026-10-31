"use client";

import { useEffect, useState } from "react";

// Public page for whoever receives a dispute letter (usually a billing office).
// Everything is checked in the browser: the signature with WebCrypto Ed25519,
// and any document the reader drops in is hashed locally and never uploaded.

interface EvidenceItem {
  source: "bill" | "eob";
  page: number | null;
  text: string;
  text_sha256: string;
}
interface Payload {
  v: number;
  packet_id: string;
  issued_at: string;
  provider: string | null;
  insurer: string | null;
  statement_date: string | null;
  letter_sha256: string;
  documents: { kind: "bill" | "eob"; sha256: string[] }[];
  items: { rule: string; evidence: EvidenceItem[] }[];
}
interface Packet {
  payload: Payload;
  signature: string;
  public_key: string;
  signature_valid: boolean;
}

// Neutral wording: this page is read by the billing office or insurer, not the patient.
const TITLES: Record<string, string> = {
  duplicate_line: "Possible duplicate charge",
  balance_mismatch: "Amount due differs from the insurance statement",
  billed_after_denial: "Charge for a service the insurer denied",
  network_mismatch: "Network status differs between bill and insurance statement",
  no_itemization: "No itemized list of charges",
  not_on_eob: "Service not on the insurance statement",
  charge_mismatch: "Charge differs from the amount billed to the insurer",
  payment_not_applied: "Insurance payment may not be applied",
  unbundled_pair: "Services usually billed together",
};

// Same bytes Python signs: json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False).
function canonical(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    return "{" + Object.keys(obj).sort().map((k) => JSON.stringify(k) + ":" + canonical(obj[k])).join(",") + "}";
  }
  return JSON.stringify(value);
}

const b64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

async function sha256Hex(data: ArrayBuffer | Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", data as BufferSource);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function verifyInBrowser(p: Packet): Promise<boolean | null> {
  try {
    const key = await crypto.subtle.importKey("raw", b64(p.public_key), { name: "Ed25519" }, false, ["verify"]);
    return await crypto.subtle.verify({ name: "Ed25519" }, key, b64(p.signature), new TextEncoder().encode(canonical(p.payload)));
  } catch {
    return null; // this browser can't do Ed25519; fall back to the server's check
  }
}

export default function VerifyPacket() {
  const [packet, setPacket] = useState<Packet | null>(null);
  const [error, setError] = useState("");
  const [browserCheck, setBrowserCheck] = useState<boolean | null>(null);
  const [fileResult, setFileResult] = useState<string>("");
  const [letterResult, setLetterResult] = useState<string>("");

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id");
    if (!id) return setError("This link is missing its reference. Check the address in the letter.");
    fetch("/api/verify/" + encodeURIComponent(id))
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 404 ? "This verification link is not valid or has expired." : "Could not load this record. Please try again.");
        return (await r.json()) as Packet;
      })
      .then(async (p) => {
        setPacket(p);
        setBrowserCheck(await verifyInBrowser(p));
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const checkFile = async (files: FileList | null) => {
    if (!packet || !files || !files.length) return;
    const hash = await sha256Hex(await files[0].arrayBuffer());
    const match = packet.payload.documents.find((d) => d.sha256.includes(hash));
    setFileResult(
      match
        ? `✓ "${files[0].name}" is exactly the ${match.kind === "eob" ? "insurance EOB" : "bill"} the patient uploaded.`
        : `✗ "${files[0].name}" does not match any uploaded document. A photo or re-saved copy will not match; only the identical file will.`,
    );
  };

  const checkLetter = async (text: string) => {
    if (!packet || !text) return setLetterResult("");
    const hash = await sha256Hex(new TextEncoder().encode(text));
    setLetterResult(hash === packet.payload.letter_sha256 ? "✓ This is exactly the letter that was issued." : "✗ This text differs from the letter that was issued (even a changed space counts).");
  };

  const valid = browserCheck ?? packet?.signature_valid ?? false;
  const p = packet?.payload;
  return (
    <main className="wrap verify">
      <header className="verify-head">
        <h1>Verify a billing letter</h1>
        <p className="tagline">
          This page lets the recipient of a patient&apos;s billing dispute letter confirm that the evidence quoted in it matches the documents the patient uploaded, and that nothing has been changed since the letter was written.
        </p>
      </header>
      {error ? <p className="banner banner-error" role="alert">{error}</p> : null}
      {!packet && !error ? <p>Checking…</p> : null}
      {p ? (
        <>
          <div id="verify-status" className={"card status " + (valid ? "ok" : "bad")}>
            <h2>{valid ? "✓ Signature valid" : "✗ Signature does not match"}</h2>
            <p>
              {valid
                ? "This record was issued by Medical Bill Checker and has not been altered since."
                : "This record has been altered or was not issued by Medical Bill Checker. Do not rely on it."}{" "}
              <span className="muted">
                Checked {browserCheck === null ? "by the server" : "in your browser"} with Ed25519.
              </span>
            </p>
            <dl className="summary">
              <dt>Issued</dt><dd>{p.issued_at.replace("T", " ").replace("+00:00", " UTC")}</dd>
              <dt>Provider</dt><dd>{p.provider ?? "—"}</dd>
              {p.insurer ? (<><dt>Insurer</dt><dd>{p.insurer}</dd></>) : null}
              <dt>Statement date</dt><dd>{p.statement_date ?? "—"}</dd>
              <dt>Reference</dt><dd><code>{p.packet_id}</code></dd>
            </dl>
          </div>

          <div className="card">
            <h2>Evidence quoted in the letter</h2>
            {p.items.map((item, i) => (
              <article key={i} className="flag">
                <h3>{TITLES[item.rule] ?? item.rule}</h3>
                <ul className="evidence">
                  {item.evidence.map((e, j) => (
                    <li key={j}>
                      <span className="src">{e.source === "eob" ? "Insurance statement" : "Bill"}{e.page ? ", page " + e.page : ""}</span>
                      <q>{e.text}</q>
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>

          <div className="card">
            <h2>Check a document you have</h2>
            <p className="muted">
              If you have the electronic statement (PDF) you sent the patient, choose it here. It is fingerprinted in your browser and is not uploaded.
            </p>
            <input id="verify-file" type="file" onChange={(e) => checkFile(e.target.files)} />
            {fileResult ? <p id="verify-file-result" className={fileResult.startsWith("✓") ? "thanks" : "note"}>{fileResult}</p> : null}
            <details className="fingerprints">
              <summary>Document fingerprints (SHA-256)</summary>
              <ul>
                {p.documents.flatMap((d, i) => d.sha256.map((h, j) => (
                  <li key={`${i}-${j}`}>{d.kind === "eob" ? "EOB" : "Bill"} file {j + 1}: <code>{h}</code></li>
                )))}
              </ul>
            </details>
          </div>

          <div className="card">
            <h2>Check the letter</h2>
            <p className="muted">Paste the full text of the letter you received to confirm it is unchanged.</p>
            <textarea id="verify-letter" rows={4} onChange={(e) => checkLetter(e.target.value)} />
            {letterResult ? <p id="verify-letter-result" className={letterResult.startsWith("✓") ? "thanks" : "note"}>{letterResult}</p> : null}
          </div>

          <p className="muted small-print">
            What this proves: the quoted evidence and fingerprints were recorded when the letter was created and have not changed. It does not prove that a charge is wrong; the letter asks you to review it.
          </p>
        </>
      ) : null}
    </main>
  );
}
