// Shapes returned by the FastAPI backend (see src/billchecker/api.py).

export type Status = "queued" | "extracting" | "needs_confirmation" | "ready" | "failed";

export interface User {
  email: string;
  research_consent: boolean;
  created_at: string;
}

export interface LineItem {
  line_id: string;
  service_date: string | null;
  description: string;
  code: string | null;
  code_type: string | null;
  units: string | null;
  charge: string;
  source_page: number;
  source_text: string;
}

export interface Totals {
  billed: string | null;
  adjustments: string | null;
  patient_balance: string | null;
}

export interface Bill {
  provider_name: string | null;
  statement_date: string | null;
  line_items: LineItem[];
  totals: Totals;
  itemized: boolean;
  extraction_confidence: "high" | "medium" | "low";
}

export interface EobLine {
  line_id: string;
  code: string | null;
  status: "processed" | "denied" | "not_processed" | "unknown";
}

export interface Eob {
  insurer: string | null;
  service_lines: EobLine[];
  totals: { patient_responsibility: string | null };
}

export interface Evidence {
  source: "bill" | "eob";
  ref: string;
  page: number | null;
  text: string;
}

export interface Flag {
  flag_id: string;
  rule: string;
  severity: "review" | "check";
  confidence: "high" | "medium" | "low";
  summary: string;
  evidence: Evidence[];
}

export interface Explanation {
  text: string;
  source: "llm" | "template";
}

export interface CaseData {
  case_id: string;
  status: Status;
  error_code: string | null;
  error_message?: string | null;
  language: "en" | "es";
  bill?: Bill;
  eob?: Eob | null;
  eob_status?: "none" | "ok" | "partial" | "unreadable";
  flags?: Flag[];
  explanations?: { lines: Record<string, Explanation>; flags: Record<string, Explanation> } | null;
  problems?: string[];
  warnings?: string[];
  user_edited?: boolean;
  price_context?: Record<string, { reference_price: string }>;
  prices_label?: string | null;
}

export interface CaseSummary {
  case_id: string;
  status: Status;
  created_at: string;
  provider_name: string | null;
  amount_due: string | null;
  flag_count: number;
}

export interface Source {
  title: string;
  section: string;
  source_name: string;
  source_url: string;
}

export interface AskResult {
  answer: string;
  fallback: boolean;
  sources: Source[];
  related: Source[];
}

export interface Letter {
  kind: string;
  subject: string;
  text: string;
}
