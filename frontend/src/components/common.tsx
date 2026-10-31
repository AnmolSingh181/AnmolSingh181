"use client";
import * as React from "react";
import { cn, tierColor, label } from "@/lib/utils";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function StatTile({ label: l, value, hint, href }: { label: string; value: React.ReactNode; hint?: string; href?: string }) {
  const body = (
    <div className={cn("rounded-lg border bg-card p-3.5", href && "transition-colors hover:border-primary/40")}>
      <p className="text-xs text-muted-foreground">{l}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
  return href ? <a href={href}>{body}</a> : body;
}

export function ScoreBadge({ score, tier }: { score: number | null; tier: string | null }) {
  if (score === null || score === undefined) return <span className="text-muted-foreground">—</span>;
  return (
    <span title={`${tier ?? ""} — prioritisation score, not a conversion probability`}
      className={cn("inline-flex min-w-9 items-center justify-center rounded-md border px-1.5 py-0.5 text-xs font-semibold tabular-nums", tierColor(tier))}>
      {score}
    </span>
  );
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed bg-card/50 p-8 text-center">
      <p className="text-sm font-medium">{title}</p>
      {children && <div className="mx-auto mt-1 max-w-lg text-sm text-muted-foreground">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="mb-3 rounded-md border border-bad/30 bg-bad/10 px-3 py-2 text-sm text-bad">{error}</div>;
}

export function Tags({ values, variant = "default", max = 4 }: { values: string[]; variant?: "default" | "primary" | "good" | "warn" | "bad" | "outline"; max?: number }) {
  if (!values?.length) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {values.slice(0, max).map((v) => <Badge key={v} variant={variant}>{label(v)}</Badge>)}
      {values.length > max && <Badge variant="outline">+{values.length - max}</Badge>}
    </span>
  );
}

const VSTATUS: Record<string, "good" | "primary" | "warn" | "bad" | "outline"> = {
  email_verified: "good", manually_verified: "good", domain_checked: "primary", phone_checked: "primary",
  syntax_checked: "outline", discovered: "outline", invalid: "bad", outdated: "warn",
};
export function VerificationBadge({ status }: { status: string }) {
  return <Badge variant={VSTATUS[status] ?? "outline"}>{label(status)}</Badge>;
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between gap-2 px-1 py-3 text-xs text-muted-foreground">
      <span>{total.toLocaleString()} result{total === 1 ? "" : "s"}</span>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
        <span>Page {page} / {pages}</span>
        <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button>
      </div>
    </div>
  );
}

/**
 * Horizontal bar list for single-series magnitudes (companies per country/material).
 * Dataviz spec: one validated hue (--series-1), bars <= 24px (14px here), 4px rounded data-end, square at baseline,
 * value at the tip in text ink, per-bar hover tooltip, recessive track. Single series -> no legend; title names it.
 */
export function BarList({ rows, valueLabel = "companies", onSelect }: {
  rows: { key: string; label: string; value: number }[]; valueLabel?: string; onSelect?: (key: string) => void;
}) {
  const [hover, setHover] = React.useState<string | null>(null);
  const max = Math.max(1, ...rows.map((r) => r.value));
  if (!rows.length) return <p className="py-6 text-center text-sm text-muted-foreground">No data collected yet.</p>;
  return (
    <ul className="flex flex-col gap-2" role="list">
      {rows.map((r) => (
        <li key={r.key} className="relative">
          <button type="button" onClick={() => onSelect?.(r.key)} onMouseEnter={() => setHover(r.key)} onMouseLeave={() => setHover(null)}
            onFocus={() => setHover(r.key)} onBlur={() => setHover(null)}
            aria-label={`${r.label}: ${r.value} ${valueLabel}`}
            className={cn("grid w-full grid-cols-[minmax(84px,34%)_1fr] items-center gap-3 rounded py-1 text-left", onSelect && "cursor-pointer")}>
            <span className="truncate text-xs text-muted-foreground">{r.label}</span>
            <span className="flex items-center gap-2">
              <span className="relative h-3.5 flex-1">
                <span className="absolute inset-y-0 left-0 rounded-r-[4px] bg-series-1 transition-opacity"
                  style={{ width: `${Math.max(2, (r.value / max) * 100)}%`, opacity: hover && hover !== r.key ? 0.45 : 1 }} />
              </span>
              <span className="w-10 text-right text-xs font-medium tabular-nums">{r.value.toLocaleString()}</span>
            </span>
          </button>
          {hover === r.key && (
            <span className="pointer-events-none absolute -top-8 left-[34%] z-10 rounded-md border bg-card px-2 py-1 text-xs shadow-md">
              <span className="font-medium">{r.label}</span> · {r.value.toLocaleString()} {valueLabel}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
