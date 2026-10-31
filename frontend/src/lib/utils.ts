import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const LABELS: Record<string, string> = {
  virgin_prime: "Virgin / Prime",
  near_prime: "Near-prime",
  off_grade: "Off-grade",
  off_spec: "Off-spec",
  non_prime_unspecified: "Non-prime (unspecified)",
  pcr: "PCR (post-consumer)",
  pir: "PIR (post-industrial)",
  blow_moulding: "Blow moulding",
  injection_moulding: "Injection moulding",
  raffia_tape: "Raffia / tape",
  wire_cable: "Wire & cable",
  historical_buyer: "Historical buyer",
  historical_seller: "Historical seller",
  scrap_aggregator: "Scrap aggregator",
  PE_SCRAP: "PE scrap",
  PE_OTHER: "Other PE",
  likely_decision_maker: "Likely decision-maker",
  confirmed_decision_maker: "Confirmed decision-maker",
  unknown_authority: "Authority unknown",
  potential_buyer: "Potential buyer",
  potential_supplier: "Potential supplier",
  not_interested: "Not interested",
  email_verified: "Email verified",
  manually_verified: "Manually verified",
  syntax_checked: "Syntax checked",
  domain_checked: "Domain checked",
  phone_checked: "Phone checked",
  awaiting_credentials: "Awaiting credentials",
  requires_terms_review: "Terms review required",
  manual_only: "Manual import only",
};

export function label(v: string | null | undefined): string {
  if (!v) return "—";
  if (LABELS[v]) return LABELS[v];
  if (/^[A-Z_]+$/.test(v)) return v;
  return v.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function fmtDate(v: string | null | undefined, withTime = false): string {
  if (!v) return "—";
  const d = new Date(v);
  if (isNaN(d.getTime())) return v;
  return withTime
    ? d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
    : d.toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function fmtNum(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function tierColor(tier: string | null | undefined): string {
  switch (tier) {
    case "High priority":
      return "bg-good/15 text-good border-good/30";
    case "Relevant":
      return "bg-accent text-accent-foreground border-primary/20";
    case "Needs verification":
      return "bg-warn/15 text-warn border-warn/30";
    default:
      return "bg-muted text-muted-foreground border-border";
  }
}
