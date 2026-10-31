"use client";
import * as React from "react";
import Link from "next/link";
import { Check, X } from "lucide-react";
import { ErrorNote, PageHeader } from "@/components/common";
import { countryName, useApp, useFetch } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import type { CompanyMaterial, CompanySummary } from "@/lib/types";
import { label } from "@/lib/utils";

type Q = Record<string, number | null> & { acceptance: { metric: string; value: number | null; target: string; met: boolean }[] };
type Sample = CompanyMaterial & { company_id: string; company_name: string; country_code: string | null };
type Dup = { id: number; score: number; reasons: string[]; a: CompanySummary & { domain: string | null; address: string | null }; b: CompanySummary & { domain: string | null; address: string | null } };

export default function QualityPage() {
  const { meta } = useApp();
  const q = useFetch<Q>("/quality");
  const sample = useFetch<Sample[]>("/quality/review-sample", { n: 15 });
  const dups = useFetch<Dup[]>("/duplicates");
  const review = async (id: number, ok: boolean) => {
    await api(`/company-materials/${id}/review`, { method: "POST", body: JSON.stringify({ status: ok ? "confirmed" : "rejected", polymer_correct: ok }) });
    sample.setData((s) => (s ?? []).filter((x) => x.id !== id));
    q.reload();
  };
  return (
    <>
      <PageHeader title="Data quality & acceptance" description="MVP acceptance criteria measured live on the database. Classification accuracy comes only from your manual reviews below." />
      <ErrorNote error={q.error} />
      <Card className="mb-4">
        <CardContent className="p-0"><Table>
          <THead><TR><TH>Metric</TH><TH>Current</TH><TH>Target</TH><TH>Status</TH></TR></THead>
          <TBody>{q.data?.acceptance.map((a) => (
            <TR key={a.metric}><TD>{a.metric}</TD><TD className="tabular-nums">{a.value ?? "—"}</TD><TD className="text-muted-foreground">{a.target}</TD>
              <TD>{a.met ? <Badge variant="good"><Check className="size-3" /> Met</Badge> : <Badge variant="warn">Not yet</Badge>}</TD></TR>))}</TBody>
        </Table></CardContent>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Classification review sample</CardTitle>
            <CardDescription>{q.data?.classification_reviews ?? 0} reviewed so far · accuracy {q.data?.classification_accuracy ?? "—"}%. Judge each row against its evidence.</CardDescription></CardHeader>
          <CardContent className="flex flex-col divide-y">
            {!sample.data?.length && <p className="py-4 text-sm text-muted-foreground">Nothing left to review.</p>}
            {sample.data?.map((m) => (
              <div key={m.id} className="py-3 text-sm">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <Link href={`/companies/${m.company_id}`} className="font-medium hover:text-primary">{m.company_name}</Link>
                    <span className="text-xs text-muted-foreground"> · {countryName(meta, m.country_code)}</span>
                    <div className="mt-1 flex flex-wrap gap-1"><Badge variant="primary">{label(m.polymer)}</Badge><Badge>{label(m.grade_category)}</Badge><Badge>{label(m.application)}</Badge><Badge variant="outline">{label(m.relationship)}</Badge><Badge variant="outline">{m.method}</Badge></div>
                  </div>
                  <span className="flex shrink-0 gap-1"><Button size="sm" variant="outline" onClick={() => review(m.id, true)}><Check /> Correct</Button><Button size="sm" variant="outline" onClick={() => review(m.id, false)}><X /> Wrong</Button></span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">“{(m.evidence_text ?? "").slice(0, 280)}”</p>
              </div>
            ))}
            <Button variant="link" size="sm" onClick={sample.reload}>Load another sample</Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Possible duplicates ({dups.data?.length ?? 0})</CardTitle>
            <CardDescription>Flagged when names match but no strong identifier (registration, domain, phone) confirmed it. Never merged automatically.</CardDescription></CardHeader>
          <CardContent className="flex flex-col divide-y">
            {!dups.data?.length && <p className="py-4 text-sm text-muted-foreground">No pending duplicate candidates.</p>}
            {dups.data?.map((d) => (
              <div key={d.id} className="py-3 text-sm">
                <p className="text-xs text-muted-foreground">{d.reasons.join("; ")} · score {d.score}</p>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  {[d.a, d.b].map((c) => (
                    <div key={c.id} className="rounded-md border p-2">
                      <Link className="font-medium hover:text-primary" href={`/companies/${c.id}`}>{c.name}</Link>
                      <p className="text-xs text-muted-foreground">{countryName(meta, c.country_code)} {c.city ?? ""} · {c.domain ?? "no domain"}</p>
                      <Button size="sm" variant="outline" className="mt-2" onClick={async () => { await api(`/duplicates/${d.id}/merge`, { method: "POST", body: JSON.stringify({ master_id: c.id }) }); dups.reload(); q.reload(); }}>Keep this, merge other</Button>
                    </div>
                  ))}
                </div>
                <Button size="sm" variant="ghost" className="mt-1" onClick={async () => { await api(`/duplicates/${d.id}/reject`, { method: "POST" }); dups.reload(); q.reload(); }}>Not duplicates</Button>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
