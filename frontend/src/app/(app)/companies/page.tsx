"use client";
import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Download, Plus, SlidersHorizontal, X } from "lucide-react";
import { Empty, ErrorNote, PageHeader, Pager, ScoreBadge, Tags } from "@/components/common";
import { countryName, useApp, useFetch } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { MultiSelect } from "@/components/ui/multi-select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, download } from "@/lib/api";
import type { CompanySummary } from "@/lib/types";
import { label } from "@/lib/utils";

const LIST_KEYS = ["country", "polymer", "grade", "application", "relationship", "company_type", "trade_role", "contact_verification", "tier", "source"] as const;
const SCALAR_KEYS = ["q", "city", "polymer_match", "has_contacts", "has_email", "has_phone", "has_website", "has_decision_maker", "contact_title", "min_score", "max_score", "sort", "order"] as const;
type Filters = Record<(typeof LIST_KEYS)[number], string[]> & Partial<Record<(typeof SCALAR_KEYS)[number], string>> & { page: number };

function fromParams(sp: URLSearchParams): Filters {
  const f = { page: Number(sp.get("page") || 1) } as Filters;
  LIST_KEYS.forEach((k) => (f[k] = sp.getAll(k)));
  SCALAR_KEYS.forEach((k) => { const v = sp.get(k); if (v) f[k] = v; });
  return f;
}
function toParams(f: Filters): URLSearchParams {
  const sp = new URLSearchParams();
  LIST_KEYS.forEach((k) => f[k].forEach((v) => sp.append(k, v)));
  SCALAR_KEYS.forEach((k) => { if (f[k]) sp.set(k, f[k] as string); });
  if (f.page > 1) sp.set("page", String(f.page));
  return sp;
}

function TriState({ label: l, value, onChange }: { label: string; value?: string; onChange: (v?: string) => void }) {
  return (
    <NativeSelect value={value ?? ""} onChange={(e) => onChange(e.target.value || undefined)} aria-label={l}>
      <option value="">{l}: any</option>
      <option value="true">{l}: yes</option>
      <option value="false">{l}: no</option>
    </NativeSelect>
  );
}

function AddCompany({ onCreated }: { onCreated: (id: string) => void }) {
  const { meta } = useApp();
  const [open, setOpen] = React.useState(false);
  const [f, setF] = React.useState({ name: "", country: "", city: "", website: "", email: "", phone: "", description: "", company_types: [] as string[] });
  const [err, setErr] = React.useState<string | null>(null);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const r = await api<{ company_id: string }>("/companies", { method: "POST", body: JSON.stringify(f) });
      setOpen(false);
      onCreated(r.company_id);
    } catch (x) { setErr((x as Error).message); }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button variant="outline" onClick={() => setOpen(true)}><Plus /> Add company</Button>
      <DialogContent title="Add a company manually" description="Description text is classified with the same rules as crawled pages; the record is attributed to you as its source.">
        <form onSubmit={save} className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1 sm:col-span-2"><Label>Company name *</Label><Input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
          <div className="flex flex-col gap-1"><Label>Country</Label>
            <NativeSelect value={f.country} onChange={(e) => setF({ ...f, country: e.target.value })}><option value="">—</option>
              {meta?.countries.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}</NativeSelect></div>
          <div className="flex flex-col gap-1"><Label>City</Label><Input value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })} /></div>
          <div className="flex flex-col gap-1"><Label>Website</Label><Input value={f.website} onChange={(e) => setF({ ...f, website: e.target.value })} /></div>
          <div className="flex flex-col gap-1"><Label>Company email</Label><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
          <div className="flex flex-col gap-1"><Label>Phone</Label><Input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></div>
          <div className="flex flex-col gap-1"><Label>Company type</Label>
            <MultiSelect placeholder="Type" options={(meta?.company_types ?? []).map((v) => ({ value: v }))} value={f.company_types} onChange={(v) => setF({ ...f, company_types: v })} /></div>
          <div className="flex flex-col gap-1 sm:col-span-2"><Label>Business / product description (evidence)</Label>
            <Textarea value={f.description} placeholder="e.g. We supply off-grade LDPE film grade from Saudi Arabia" onChange={(e) => setF({ ...f, description: e.target.value })} /></div>
          {err && <p className="text-sm text-bad sm:col-span-2">{err}</p>}
          <div className="sm:col-span-2"><Button type="submit">Save company</Button></div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function CompaniesInner() {
  const { meta } = useApp();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [f, setF] = React.useState<Filters>(() => fromParams(new URLSearchParams(sp.toString())));
  const [showFilters, setShowFilters] = React.useState(true);
  const advActive = (["city", "polymer_match", "has_contacts", "has_email", "has_phone", "has_website", "has_decision_maker",
    "contact_title", "min_score", "max_score"] as const).some((k) => !!f[k]) ||
    (["grade", "application", "trade_role", "contact_verification", "tier", "source"] as const).some((k) => f[k].length > 0);
  const [more, setMore] = React.useState(advActive);
  const [q, setQ] = React.useState(f.q ?? "");
  React.useEffect(() => {
    const s = toParams(f).toString();
    router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false });
  }, [f, pathname, router]);
  React.useEffect(() => { const t = setTimeout(() => setF((p) => (p.q === (q || undefined) ? p : { ...p, q: q || undefined, page: 1 })), 350); return () => clearTimeout(t); }, [q]);

  const params = { ...Object.fromEntries(LIST_KEYS.map((k) => [k, f[k]])), ...Object.fromEntries(SCALAR_KEYS.map((k) => [k, f[k]])), page: f.page, page_size: 25 };
  const { data, error, loading } = useFetch<{ total: number; items: CompanySummary[] }>("/companies", params);
  const set = (patch: Partial<Filters>) => setF((p) => ({ ...p, ...patch, page: 1 }));
  const active = LIST_KEYS.some((k) => f[k].length) || SCALAR_KEYS.some((k) => f[k] && k !== "sort" && k !== "order");
  const opt = (vals: string[] | undefined) => (vals ?? []).map((v) => ({ value: v }));

  return (
    <>
      <PageHeader title="Company discovery" description="Combine filters freely. Material filters (polymer + grade + application + buyer/seller) must all hold on the same evidenced material record."
        actions={<>
          <Button variant="outline" onClick={() => setShowFilters(!showFilters)}><SlidersHorizontal /> {showFilters ? "Hide" : "Show"} filters</Button>
          <Button variant="outline" onClick={() => download("/companies/export.csv", params, "companies.csv")}><Download /> Export CSV</Button>
          <AddCompany onCreated={(id) => router.push(`/companies/${id}`)} />
        </>} />
      {showFilters && (
        <div className="mb-3 rounded-lg border bg-card p-3">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-6">
            <Input className="sm:col-span-2" placeholder="Search name, domain, description, CMP-ref…" value={q} onChange={(e) => setQ(e.target.value)} />
            <MultiSelect placeholder="Country" value={f.country} onChange={(v) => set({ country: v })}
              options={(meta?.countries ?? []).map((c) => ({ value: c.code, label: c.name }))} />
            <MultiSelect placeholder="Polymer" value={f.polymer} onChange={(v) => set({ polymer: v })}
              options={(meta?.materials ?? []).map((m) => ({ value: m.code, label: label(m.code) }))} />
            <MultiSelect placeholder="Buyer / seller" value={f.relationship} onChange={(v) => set({ relationship: v })}
              options={["buyer", "seller", "both", "manufacturer", "historical_buyer", "historical_seller"].map((v) => ({ value: v }))} />
            <MultiSelect placeholder="Company type" value={f.company_type} onChange={(v) => set({ company_type: v })} options={opt(meta?.company_types)} />
          </div>
          {more && (
            <div className="mt-2 grid grid-cols-1 gap-2 border-t pt-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
            <Input placeholder="City" value={f.city ?? ""} onChange={(e) => set({ city: e.target.value || undefined })} />
            <NativeSelect value={f.polymer_match ?? "any"} onChange={(e) => set({ polymer_match: e.target.value === "all" ? "all" : undefined })} aria-label="Polymer match">
              <option value="any">Deals in any selected polymer</option><option value="all">Deals in all selected polymers</option>
            </NativeSelect>
            <MultiSelect placeholder="Grade" value={f.grade} onChange={(v) => set({ grade: v })} options={opt(meta?.grade_categories)} />
            <MultiSelect placeholder="Application" value={f.application} onChange={(v) => set({ application: v })} options={opt(meta?.applications)} />
            <MultiSelect placeholder="Importer / exporter" value={f.trade_role} onChange={(v) => set({ trade_role: v })} options={[{ value: "importer" }, { value: "exporter" }]} />
            <MultiSelect placeholder="Contact verification" value={f.contact_verification} onChange={(v) => set({ contact_verification: v })} options={opt(meta?.verification_statuses)} />
            <TriState label="Contacts" value={f.has_contacts} onChange={(v) => set({ has_contacts: v })} />
            <TriState label="Email" value={f.has_email} onChange={(v) => set({ has_email: v })} />
            <TriState label="Phone" value={f.has_phone} onChange={(v) => set({ has_phone: v })} />
            <TriState label="Website" value={f.has_website} onChange={(v) => set({ has_website: v })} />
            <NativeSelect value={f.has_decision_maker ?? ""} onChange={(e) => set({ has_decision_maker: e.target.value || undefined })} aria-label="Decision maker">
              <option value="">Decision-maker: any</option><option value="true">Has decision-maker contact</option>
            </NativeSelect>
            <Input placeholder="Contact title contains…" value={f.contact_title ?? ""} onChange={(e) => set({ contact_title: e.target.value || undefined })} />
            <Input type="number" min={0} max={100} placeholder="Min score" value={f.min_score ?? ""} onChange={(e) => set({ min_score: e.target.value || undefined })} />
            <MultiSelect placeholder="Score tier" value={f.tier} onChange={(v) => set({ tier: v })} options={(meta?.tiers ?? []).map((t) => ({ value: t, label: t }))} />
            <MultiSelect placeholder="Data source" value={f.source} onChange={(v) => set({ source: v })} options={(meta?.sources ?? []).map((s) => ({ value: s.key, label: s.name }))} />
            </div>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <Button variant="link" size="sm" onClick={() => setMore(!more)}>{more ? "Fewer filters" : `More filters${advActive ? " (active)" : ""}`}</Button>
            {active && <Button variant="link" size="sm" onClick={() => { setQ(""); setF(fromParams(new URLSearchParams())); }}><X /> Clear all filters</Button>}
          </div>
        </div>
      )}
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">{data ? `${data.total.toLocaleString()} compan${data.total === 1 ? "y" : "ies"} found` : "Loading…"}
          {f.country.length > 0 && ` in ${f.country.map((c) => countryName(meta, c)).join(", ")}`}</p>
        <div className="w-56">
            <NativeSelect value={`${f.sort ?? "score"}:${f.order ?? "desc"}`} onChange={(e) => { const [s, o] = e.target.value.split(":"); set({ sort: s, order: o }); }} aria-label="Sort">
              <option value="score:desc">Sort: lead score ↓</option><option value="name:asc">Sort: name A–Z</option>
              <option value="discovered:desc">Sort: newest</option><option value="verified:desc">Sort: recently verified</option>
              <option value="country:asc">Sort: country</option>
            </NativeSelect>
        </div>
      </div>
      <ErrorNote error={error} />
      {data && data.total === 0 ? (
        <Empty title="No companies match these filters">Results only include records with collected evidence. Widen the filters or collect more data in Data sources.</Empty>
      ) : (
        <div className="rounded-lg border bg-card">
          <Table>
            <THead><TR><TH>Score</TH><TH>Company</TH><TH>Country</TH><TH>Type</TH><TH>Polymers</TH><TH>Grades</TH><TH>Buyer / seller</TH><TH>Contacts</TH></TR></THead>
            <TBody>
              {(data?.items ?? []).map((c) => (
                <TR key={c.id}>
                  <TD><ScoreBadge score={c.lead_score} tier={c.lead_tier} /></TD>
                  <TD className="min-w-56"><Link href={`/companies/${c.id}`} className="font-medium hover:text-primary">{c.name}</Link>
                    <p className="text-xs text-muted-foreground">{c.public_ref}{c.website ? ` · ${c.website.replace(/^https?:\/\//, "")}` : ""}</p></TD>
                  <TD className="whitespace-nowrap">{countryName(meta, c.country_code)}{c.city ? <span className="block text-xs text-muted-foreground">{c.city}</span> : null}</TD>
                  <TD><Tags values={c.company_types} max={2} /></TD>
                  <TD><Tags values={c.polymers} variant="primary" /></TD>
                  <TD><Tags values={c.grades} max={2} /></TD>
                  <TD><Tags values={c.relationships} max={2} variant="outline" /></TD>
                  <TD className="whitespace-nowrap text-xs">{c.contact_count}{c.decision_makers ? <span className="text-muted-foreground"> · {c.decision_makers} DM</span> : null}</TD>
                </TR>
              ))}
              {loading && !data && <TR><TD colSpan={8} className="py-8 text-center text-muted-foreground">Loading…</TD></TR>}
            </TBody>
          </Table>
          {data && <Pager page={f.page} pageSize={25} total={data.total} onPage={(p) => setF({ ...f, page: p })} />}
        </div>
      )}
    </>
  );
}

export default function CompaniesPage() {
  return <React.Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}><CompaniesInner /></React.Suspense>;
}
