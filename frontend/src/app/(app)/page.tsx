"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { BarList, Empty, ErrorNote, PageHeader, ScoreBadge, StatTile } from "@/components/common";
import { countryName, useApp, useFetch } from "@/components/providers";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fmtDate, label } from "@/lib/utils";

type Dash = {
  totals: Record<string, number>;
  contact_verification: Record<string, number>;
  by_country: { country: string; count: number }[];
  by_material: { material: string; companies: number }[];
  by_grade: { grade: string; companies: number }[];
  recent_companies: { id: string; name: string; country_code: string | null; lead_score: number | null; lead_tier: string | null; first_discovered_at: string }[];
  high_priority_leads: { id: string; name: string; country_code: string | null; lead_score: number | null; lead_tier: string | null }[];
  recent_shipments: { id: number; date: string | null; importer: string | null; exporter: string | null; hs_code: string | null; material: string | null; importer_country: string | null; exporter_country: string | null; importer_company_id: string | null; exporter_company_id: string | null }[];
  collection: { jobs_last_7_days: Record<string, number>; sources_by_status: Record<string, number>; last_successful_collection: string | null; queued: number; running: number };
};

export default function Dashboard() {
  const { meta } = useApp();
  const router = useRouter();
  const { data, error } = useFetch<Dash>("/dashboard");
  const t = data?.totals;
  return (
    <>
      <PageHeader title="Dashboard" description="Live figures from the database. Every number links back to collected, source-traceable records." />
      <ErrorNote error={error} />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatTile label="Companies" value={t?.companies ?? "…"} href="/companies" />
        <StatTile label="Buyers" value={t?.buyers ?? "…"} hint="incl. historical" href="/companies?relationship=buyer" />
        <StatTile label="Sellers" value={t?.sellers ?? "…"} hint="incl. manufacturers" href="/companies?relationship=seller" />
        <StatTile label="Manufacturers" value={t?.manufacturers ?? "…"} hint="resin producers" href="/companies?company_type=manufacturer" />
        <StatTile label="Traders & distributors" value={t?.traders ?? "…"} href="/companies?company_type=trader" />
        <StatTile label="Recyclers & processors" value={t?.recyclers ?? "…"} href="/companies?company_type=recycler" />
        <StatTile label="Contacts" value={t?.contacts ?? "…"} href="/contacts" />
        <StatTile label="Verified contacts" value={t?.verified_contacts ?? "…"} hint="provider or manual" href="/contacts?verification=email_verified&verification=manually_verified" />
        <StatTile label="High-priority leads" value={t?.high_priority ?? "…"} hint="score ≥ 80" href="/companies?min_score=80" />
        <StatTile label="Importers" value={t?.importers ?? "…"} href="/companies?trade_role=importer" />
        <StatTile label="Exporters" value={t?.exporters ?? "…"} href="/companies?trade_role=exporter" />
        <StatTile label="Shipment records" value={t?.shipments ?? "…"} href="/trade" />
      </div>

      {data && t?.companies === 0 && (
        <div className="mt-5"><Empty title="No companies collected yet">
          Start from <Link className="text-primary underline" href="/sources">Data sources</Link>: import a permitted CSV export, crawl a company
          website, or add a search API key to enable automated discovery.
        </Empty></div>
      )}

      <div className="mt-5 grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Companies by country</CardTitle><CardDescription>Click a bar to filter discovery</CardDescription></CardHeader>
          <CardContent><BarList rows={(data?.by_country ?? []).slice(0, 10).map((r) => ({ key: r.country, label: countryName(meta, r.country === "Unknown" ? null : r.country) === "—" ? "Unknown" : countryName(meta, r.country), value: r.count }))}
            onSelect={(k) => k !== "Unknown" && router.push(`/companies?country=${k}`)} /></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Companies by material</CardTitle><CardDescription>Distinct companies per polymer</CardDescription></CardHeader>
          <CardContent><BarList rows={(data?.by_material ?? []).map((r) => ({ key: r.material, label: label(r.material), value: r.companies }))}
            onSelect={(k) => router.push(`/companies?polymer=${k}`)} /></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Companies by grade category</CardTitle><CardDescription>Virgin, off-grade, recycled…</CardDescription></CardHeader>
          <CardContent><BarList rows={(data?.by_grade ?? []).filter((r) => r.grade !== "unknown").map((r) => ({ key: r.grade, label: label(r.grade), value: r.companies }))}
            onSelect={(k) => router.push(`/companies?grade=${k}`)} /></CardContent>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>High-priority leads</CardTitle></CardHeader>
          <CardContent className="flex flex-col divide-y">
            {!data?.high_priority_leads.length && <p className="py-4 text-sm text-muted-foreground">No company has reached a score of 80 yet.</p>}
            {data?.high_priority_leads.map((c) => (
              <Link key={c.id} href={`/companies/${c.id}`} className="flex items-center justify-between gap-2 py-2 text-sm hover:text-primary">
                <span className="min-w-0 truncate">{c.name} <span className="text-xs text-muted-foreground">· {countryName(meta, c.country_code)}</span></span>
                <ScoreBadge score={c.lead_score} tier={c.lead_tier} />
              </Link>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Recently discovered</CardTitle></CardHeader>
          <CardContent className="flex flex-col divide-y">
            {!data?.recent_companies.length && <p className="py-4 text-sm text-muted-foreground">Nothing yet.</p>}
            {data?.recent_companies.map((c) => (
              <Link key={c.id} href={`/companies/${c.id}`} className="flex items-center justify-between gap-2 py-2 text-sm hover:text-primary">
                <span className="min-w-0 truncate">{c.name} <span className="text-xs text-muted-foreground">· {countryName(meta, c.country_code)} · {fmtDate(c.first_discovered_at)}</span></span>
                <ScoreBadge score={c.lead_score} tier={c.lead_tier} />
              </Link>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Recent import / export activity</CardTitle></CardHeader>
          <CardContent className="flex flex-col divide-y">
            {!data?.recent_shipments.length && <p className="py-4 text-sm text-muted-foreground">No shipment records yet. Import a trade-data export from Data sources.</p>}
            {data?.recent_shipments.map((s) => (
              <div key={s.id} className="py-2 text-sm">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-xs text-muted-foreground">{fmtDate(s.date)}</span>
                  {s.material && <Badge variant="primary">{label(s.material)}</Badge>}
                  {s.hs_code && <Badge variant="outline">HS {s.hs_code}</Badge>}
                </div>
                <p className="mt-0.5 truncate">
                  {s.exporter_company_id ? <Link className="hover:text-primary" href={`/companies/${s.exporter_company_id}`}>{s.exporter ?? "?"}</Link> : s.exporter ?? "?"}
                  <span className="text-muted-foreground"> ({s.exporter_country ?? "?"}) → </span>
                  {s.importer_company_id ? <Link className="hover:text-primary" href={`/companies/${s.importer_company_id}`}>{s.importer ?? "?"}</Link> : s.importer ?? "?"}
                  <span className="text-muted-foreground"> ({s.importer_country ?? "?"})</span>
                </p>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Data collection status</CardTitle><CardDescription>Last successful collection: {fmtDate(data?.collection.last_successful_collection, true)}</CardDescription></CardHeader>
          <CardContent className="flex flex-col gap-3 text-sm">
            <div className="flex flex-wrap gap-1.5">
              <Badge variant="primary">Queued {data?.collection.queued ?? 0}</Badge>
              <Badge variant="primary">Running {data?.collection.running ?? 0}</Badge>
              {Object.entries(data?.collection.jobs_last_7_days ?? {}).map(([k, v]) => (
                <Badge key={k} variant={k === "failed" ? "bad" : k === "succeeded" ? "good" : "default"}>{label(k)} (7d) {v}</Badge>
              ))}
            </div>
            <div>
              <p className="mb-1 text-xs text-muted-foreground">Sources by status</p>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(data?.collection.sources_by_status ?? {}).map(([k, v]) => <Badge key={k} variant="outline">{label(k)}: {v}</Badge>)}
              </div>
            </div>
            <Link href="/sources" className="text-xs text-primary hover:underline">Manage data sources →</Link>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
