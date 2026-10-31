"use client";
import * as React from "react";
import Link from "next/link";
import { Sparkles } from "lucide-react";
import { Empty, ErrorNote, PageHeader, ScoreBadge, Tags, VerificationBadge } from "@/components/common";
import { countryName, useApp } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { CompanySummary } from "@/lib/types";
import { label } from "@/lib/utils";

type Result = CompanySummary & {
  top_contacts: { name: string | null; title: string | null; email: string | null; phone: string | null; verification_status: string; source_url: string | null }[];
  evidence: { polymer: string; grade: string; relationship: string; text: string; url: string | null }[];
};
type Resp = { query: string; parser: string; interpretation: string[]; filters: Record<string, unknown>; total: number; items: Result[]; note: string };

const EXAMPLES = [
  "Find virgin LLDPE film grade suppliers in the USA.",
  "Find companies importing off-grade LDPE into India.",
  "Find recycled HDPE buyers in Vietnam.",
  "Find plastic traders in UAE dealing in both LDPE and LLDPE.",
  "Show companies that have public procurement manager contact information.",
];

export default function SearchPage() {
  const { meta } = useApp();
  const [q, setQ] = React.useState("");
  const [res, setRes] = React.useState<Resp | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const run = async (query: string) => {
    setQ(query);
    setBusy(true);
    setErr(null);
    try { setRes(await api<Resp>("/search/nl", { method: "POST", body: JSON.stringify({ query }) })); }
    catch (x) { setErr((x as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <>
      <PageHeader title="AI search assistant" description="Ask in plain language. The question is translated into database filters; every result is a stored company record with its evidence and source." />
      <form onSubmit={(e) => { e.preventDefault(); if (q.trim()) run(q); }} className="flex gap-2">
        <Input className="h-10" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. near-prime HDPE blow moulding sellers in Saudi Arabia" />
        <Button size="lg" type="submit" disabled={busy}><Sparkles /> {busy ? "Searching…" : "Search"}</Button>
      </form>
      <div className="mt-3 flex flex-wrap gap-2">
        {EXAMPLES.map((e) => <button key={e} onClick={() => run(e)} className="rounded-full border bg-card px-3 py-1 text-xs text-muted-foreground hover:border-primary/40 hover:text-foreground">{e}</button>)}
      </div>
      <ErrorNote error={err} />
      {res && (
        <div className="mt-5">
          <div className="mb-3 rounded-lg border bg-card p-3 text-sm">
            <p><span className="font-medium">Interpreted as</span> <Badge variant="outline">{res.parser === "ai" ? "AI parser" : "rule parser"}</Badge></p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">{res.interpretation.length ? res.interpretation.map((i) => <Badge key={i} variant="primary">{i}</Badge>) : <span className="text-muted-foreground">No specific filters recognised; showing all companies.</span>}</div>
            <p className="mt-2 text-xs text-muted-foreground">{res.total} matching record(s). {res.note}</p>
            <Link className="mt-1 inline-block text-xs text-primary hover:underline" href={`/companies?${new URLSearchParams(Object.entries(res.filters).flatMap(([k, v]) => {
              const map: Record<string, string> = { countries: "country", polymers: "polymer", grades: "grade", applications: "application", relationships: "relationship", company_types: "company_type", trade_roles: "trade_role", contact_verification: "contact_verification" };
              const key = map[k] ?? k;
              return Array.isArray(v) ? v.map((x) => [key, String(x)]) : [[key, String(v)]];
            })).toString()}`}>Open these filters in Company discovery →</Link>
          </div>
          {res.total === 0 ? <Empty title="No matching records in the database">Nothing is invented: collect more data (Data sources) or broaden the question.</Empty> : (
            <div className="flex flex-col gap-3">
              {res.items.map((c) => (
                <Card key={c.id}><CardContent className="pt-4">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <Link href={`/companies/${c.id}`} className="font-medium hover:text-primary">{c.name}</Link>
                      <p className="text-xs text-muted-foreground">{countryName(meta, c.country_code)}{c.city ? ` · ${c.city}` : ""}{c.website ? ` · ${c.website.replace(/^https?:\/\//, "")}` : ""}</p>
                      <div className="mt-1.5 flex flex-wrap gap-1"><Tags values={c.company_types} /><Tags values={c.polymers} variant="primary" /><Tags values={c.relationships} variant="outline" /></div>
                    </div>
                    <ScoreBadge score={c.lead_score} tier={c.lead_tier} />
                  </div>
                  {c.evidence.map((e, i) => (
                    <blockquote key={i} className="mt-2 border-l-2 border-primary/40 pl-2 text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">{label(e.polymer)} · {label(e.grade)} · {label(e.relationship)}:</span> “{e.text}”
                      {e.url && <a href={e.url} target="_blank" rel="noreferrer" className="ml-1 text-primary hover:underline">source</a>}
                    </blockquote>
                  ))}
                  {c.top_contacts.length > 0 && (
                    <div className="mt-2 flex flex-col gap-1 text-xs">
                      {c.top_contacts.map((p, i) => (
                        <div key={i} className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{p.name ?? "General contact"}</span>{p.title && <span className="text-muted-foreground">{p.title}</span>}
                          {p.email && <a className="text-primary" href={`mailto:${p.email}`}>{p.email}</a>}{p.phone && <span>{p.phone}</span>}
                          <VerificationBadge status={p.verification_status} />
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent></Card>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  );
}
