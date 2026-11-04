"use client";
import * as React from "react";
import { Play, Upload } from "lucide-react";
import { ErrorNote, PageHeader } from "@/components/common";
import { useApp, useFetch } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import type { Job } from "@/lib/types";
import { fmtDate, label } from "@/lib/utils";

type Src = { id: number; key: string; name: string; source_type: string; access_method: string; base_url: string | null; status: string;
  enabled: boolean; requires_credentials: boolean; credential_env_vars: string[]; terms_notes: string | null; pricing_notes: string | null;
  config: Record<string, unknown>; refresh_interval_days: number | null; last_run_at: string | null; last_success_at: string | null;
  last_error: string | null; total_records: number; readiness: { ready: boolean; message: string }; failed_jobs_30d: number;
  raw_records: number; default_job: string | null };
type Resp = { sources: Src[]; api_usage_month: { provider: string; requests: number; units: number; cost_usd: number }[];
  summary: { pending_duplicates: number; materials_awaiting_review: number; raw_pending: number; raw_failed: number; contacts_awaiting_verification: number } };

const STATUS_VARIANT: Record<string, "good" | "warn" | "bad" | "outline" | "primary"> = {
  active: "good", awaiting_credentials: "warn", requires_terms_review: "warn", manual_only: "primary", error: "bad", disabled: "outline" };

function ImportCard({ onDone }: { onDone: () => void }) {
  const [kind, setKind] = React.useState("shipments");
  const [origin, setOrigin] = React.useState("importyeti");
  const [file, setFile] = React.useState<File | null>(null);
  const [res, setRes] = React.useState<Job | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("kind", kind);
    if (origin) fd.append("origin_source", origin);
    setBusy(true); setErr(null);
    try { setRes(await api<Job>("/imports", { method: "POST", body: fd })); onDone(); }
    catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
  };
  return (
    <Card>
      <CardHeader><CardTitle>Import a permitted export (CSV / XLSX)</CardTitle>
        <CardDescription>Shipments from ImportYeti, Volza, Panjiva or TradeData.Pro exports, or company lists (Kompass exports, directories, trade-fair lists, your CRM). Columns are auto-mapped; each row is kept as a raw record.</CardDescription></CardHeader>
      <CardContent>
        <form onSubmit={submit} className="grid gap-2 sm:grid-cols-4">
          <NativeSelect value={kind} onChange={(e) => setKind(e.target.value)}><option value="shipments">Shipment records</option><option value="companies">Company list</option></NativeSelect>
          <NativeSelect value={origin} onChange={(e) => setOrigin(e.target.value)}>
            <option value="">Origin: generic CSV</option>
            {["importyeti", "volza", "panjiva", "tradedata_pro", "kompass", "enf_plastic", "plasticker", "plastics_markets", "epda", "apollo"].map((k) => <option key={k} value={k}>Origin: {label(k)}</option>)}
          </NativeSelect>
          <Input type="file" accept=".csv,.xlsx,.xlsm,.tsv,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <Button type="submit" disabled={!file || busy}><Upload /> {busy ? "Importing…" : "Import"}</Button>
        </form>
        {err && <p className="mt-2 text-sm text-bad">{err}</p>}
        {res && <p className="mt-2 text-sm">Job #{res.id}: <Badge variant={res.status === "succeeded" ? "good" : res.status === "failed" ? "bad" : "warn"}>{res.status}</Badge> — {res.records_found} rows, {res.records_created} created, {res.records_updated} updated/skipped, {res.records_failed} failed{res.error_message ? ` · ${res.error_message}` : ""}</p>}
      </CardContent>
    </Card>
  );
}

function RunDialog({ s, onDone }: { s: Src; onDone: () => void }) {
  const [open, setOpen] = React.useState(false);
  const [params, setParams] = React.useState("{}");
  const [msg, setMsg] = React.useState<string | null>(null);
  const run = async (now: boolean) => {
    try {
      const j = await api<Job>(`/sources/${s.key}/run`, { method: "POST", body: JSON.stringify({ params: JSON.parse(params || "{}"), run_now: now }) });
      setMsg(`Job #${j.id}: ${j.status}${j.error_message ? " — " + j.error_message : ""}`);
      onDone();
    } catch (x) { setMsg((x as Error).message); }
  };
  const examples: Record<string, string> = {
    company_website: '{"url": "https://www.example-company.com", "country": "AE"}  (job type crawl_website) or {"older_than_days": 45}',
    web_search: '{"countries": ["IN","VN"], "polymers": ["LLDPE"], "grades": ["off_grade"], "intents": ["buyer"], "max_queries": 10}',
    us_census: '{"hs_codes": ["390110","390120"], "months": 3}',
    un_comtrade: '{"period": "2025", "reporters": [699, 704]}',
    apollo: '{"limit": 25, "max_enrich": 25}  (limit = companies searched; max_enrich = people revealed, each uses Apollo credits)',
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)} disabled={!s.default_job}><Play /> Run</Button>
      <DialogContent title={`Run ${s.name}`} description={`Job type: ${s.default_job}. Queued jobs are executed by the worker; “Run now” executes immediately (may take a while).`}>
        <Label>Parameters (JSON)</Label>
        <Textarea className="mt-1 font-mono text-xs" value={params} onChange={(e) => setParams(e.target.value)} />
        {examples[s.key] && <p className="mt-1 text-xs text-muted-foreground">Example: {examples[s.key]}</p>}
        <div className="mt-3 flex gap-2"><Button onClick={() => run(false)}>Queue</Button><Button variant="outline" onClick={() => run(true)}>Run now</Button></div>
        {msg && <p className="mt-2 text-sm">{msg}</p>}
      </DialogContent>
    </Dialog>
  );
}

function CrawlOne({ onDone }: { onDone: () => void }) {
  const { meta } = useApp();
  const [url, setUrl] = React.useState("");
  const [cc, setCc] = React.useState("");
  const [msg, setMsg] = React.useState<string | null>(null);
  return (
    <Card>
      <CardHeader><CardTitle>Crawl a company website</CardTitle><CardDescription>Fetches home, about, products, contact pages (robots.txt respected), then classifies and deduplicates.</CardDescription></CardHeader>
      <CardContent>
        <form className="grid gap-2 sm:grid-cols-[1fr_180px_auto]" onSubmit={async (e) => { e.preventDefault();
          try { const j = await api<Job>("/sources/company_website/run", { method: "POST", body: JSON.stringify({ job_type: "crawl_website", params: { url, country: cc || null } }) });
            setMsg(`Queued job #${j.id}. The worker will process it shortly.`); setUrl(""); onDone(); } catch (x) { setMsg((x as Error).message); } }}>
          <Input required placeholder="https://company-website.com" value={url} onChange={(e) => setUrl(e.target.value)} />
          <NativeSelect value={cc} onChange={(e) => setCc(e.target.value)}><option value="">Country hint (optional)</option>{meta?.countries.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}</NativeSelect>
          <Button type="submit">Queue crawl</Button>
        </form>
        {msg && <p className="mt-2 text-sm text-muted-foreground">{msg}</p>}
      </CardContent>
    </Card>
  );
}

export default function SourcesPage() {
  const { me } = useApp();
  const { data, error, reload } = useFetch<Resp>("/sources");
  const jobs = useFetch<{ counts: Record<string, number>; items: Job[] }>("/jobs", { limit: 30 });
  const [jobOpen, setJobOpen] = React.useState<number | null>(null);
  const isAdmin = me?.role === "admin";
  const refresh = () => { reload(); jobs.reload(); };
  const patch = async (s: Src, body: Record<string, unknown>) => {
    try { await api(`/sources/${s.id}`, { method: "PATCH", body: JSON.stringify(body) }); refresh(); } catch (x) { alert((x as Error).message); }
  };
  return (
    <>
      <PageHeader title="Data sources" description="Every connector, its real status, and what it needs. Sources that need credentials or a terms-of-use review stay disabled until set up; nothing pretends to work."
        actions={<Button variant="outline" onClick={refresh}>Refresh</Button>} />
      <ErrorNote error={error} />
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
        {data && ([["Pending duplicates", data.summary.pending_duplicates], ["Materials awaiting review", data.summary.materials_awaiting_review],
          ["Contacts awaiting verification", data.summary.contacts_awaiting_verification], ["Raw records pending", data.summary.raw_pending],
          ["Failed jobs (all time)", jobs.data?.counts.failed ?? 0]] as [string, number][]).map(([k, v]) => (
          <div key={k} className="rounded-lg border bg-card p-3"><p className="text-xs text-muted-foreground">{k}</p><p className="text-xl font-semibold tabular-nums">{v}</p></div>
        ))}
      </div>
      <div className="mb-4 grid gap-4 lg:grid-cols-2"><ImportCard onDone={refresh} /><CrawlOne onDone={refresh} /></div>

      <Card className="mb-4">
        <CardHeader><CardTitle>Connected and pending sources</CardTitle></CardHeader>
        <CardContent className="p-0">
          <Table>
            <THead><TR><TH>Source</TH><TH>Status</TH><TH>Readiness</TH><TH>Last run / success</TH><TH>Records</TH><TH>Failed 30d</TH><TH /></TR></THead>
            <TBody>{data?.sources.map((s) => (
              <TR key={s.id}>
                <TD className="min-w-56"><p className="font-medium">{s.name}</p><p className="text-xs text-muted-foreground">{label(s.source_type)} · {label(s.access_method)}{s.base_url && <> · <a className="hover:underline" href={s.base_url} target="_blank" rel="noreferrer">{s.base_url.replace(/^https?:\/\//, "")}</a></>}</p>
                  {s.terms_notes && <details className="mt-1 text-xs text-muted-foreground"><summary className="cursor-pointer">Terms & notes</summary><p className="mt-1">{s.terms_notes}</p>{s.pricing_notes && <p className="mt-1">Pricing: {s.pricing_notes}</p>}
                    {s.credential_env_vars.length > 0 && <p className="mt-1">Env vars: <code>{s.credential_env_vars.join(", ")}</code></p>}
                    {s.config?.terms_confirmed ? <p className="mt-1 text-good">Terms confirmed by {String(s.config.terms_confirmed_by)} on {fmtDate(String(s.config.terms_confirmed_at))}</p> : null}</details>}</TD>
                <TD><Badge variant={STATUS_VARIANT[s.status] ?? "outline"}>{label(s.status)}</Badge>{s.enabled && <Badge variant="outline" className="ml-1">enabled</Badge>}</TD>
                <TD className="max-w-64 text-xs">{s.readiness.ready ? <span className="text-good">Ready</span> : <span className="text-muted-foreground">{s.readiness.message}</span>}
                  {s.last_error && <p className="mt-1 text-bad">{s.last_error.slice(0, 160)}</p>}</TD>
                <TD className="whitespace-nowrap text-xs">{fmtDate(s.last_run_at, true)}<br /><span className="text-muted-foreground">{fmtDate(s.last_success_at, true)}</span></TD>
                <TD className="tabular-nums">{s.total_records}<span className="block text-xs text-muted-foreground">{s.raw_records} raw</span></TD>
                <TD className="tabular-nums">{s.failed_jobs_30d}</TD>
                <TD className="whitespace-nowrap">
                  <div className="flex flex-wrap gap-1">
                    <RunDialog s={s} onDone={refresh} />
                    {isAdmin && s.status === "requires_terms_review" && <Button size="sm" variant="outline" onClick={() => {
                      const note = prompt(`Confirm you reviewed ${s.base_url} terms of use and automated collection is permitted. Add a note (e.g. link to terms / written permission):`);
                      if (note) patch(s, { confirm_terms: true, terms_note: note }); }}>Confirm terms</Button>}
                    {isAdmin && <Button size="sm" variant="ghost" onClick={() => patch(s, { enabled: !s.enabled })}>{s.enabled ? "Disable" : "Enable"}</Button>}
                  </div>
                </TD>
              </TR>))}</TBody>
          </Table>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Recent jobs</CardTitle><CardDescription>{Object.entries(jobs.data?.counts ?? {}).map(([k, v]) => `${label(k)} ${v}`).join(" · ")}</CardDescription></CardHeader>
          <CardContent className="p-0"><Table>
            <THead><TR><TH>#</TH><TH>Source / type</TH><TH>Status</TH><TH>Found / created / updated / failed</TH><TH>Finished</TH><TH /></TR></THead>
            <TBody>{jobs.data?.items.map((j) => (
              <React.Fragment key={j.id}>
                <TR>
                  <TD>{j.id}</TD><TD className="text-xs">{j.source}<span className="block text-muted-foreground">{j.job_type}</span></TD>
                  <TD><Badge variant={j.status === "succeeded" ? "good" : j.status === "failed" ? "bad" : j.status === "partial" ? "warn" : "outline"}>{j.status}</Badge></TD>
                  <TD className="tabular-nums text-xs">{j.records_found} / {j.records_created} / {j.records_updated} / {j.records_failed}</TD>
                  <TD className="text-xs">{fmtDate(j.finished_at, true)}</TD>
                  <TD className="whitespace-nowrap"><Button size="sm" variant="ghost" onClick={() => setJobOpen(jobOpen === j.id ? null : j.id)}>Log</Button>
                    {(j.status === "failed" || j.status === "partial") && <Button size="sm" variant="ghost" onClick={async () => { await api(`/jobs/${j.id}/retry`, { method: "POST" }); refresh(); }}>Retry</Button>}</TD>
                </TR>
                {jobOpen === j.id && <TR><TD colSpan={6}><pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-muted p-2 text-[11px]">{j.error_message ? `ERROR: ${j.error_message}\n\n` : ""}{j.log.map((l) => `${l.t} ${l.level.toUpperCase()} ${l.msg}`).join("\n") || "No log entries."}</pre></TD></TR>}
              </React.Fragment>))}
              {!jobs.data?.items.length && <TR><TD colSpan={6} className="py-6 text-center text-muted-foreground">No jobs yet.</TD></TR>}
            </TBody>
          </Table></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>API usage this month</CardTitle><CardDescription>Estimated from recorded calls; check provider dashboards for billing.</CardDescription></CardHeader>
          <CardContent className="flex flex-col divide-y text-sm">
            {!data?.api_usage_month.length && <p className="text-muted-foreground">No paid API calls recorded.</p>}
            {data?.api_usage_month.map((u) => <div key={u.provider} className="flex justify-between py-1.5"><span>{label(u.provider)}</span><span className="tabular-nums text-muted-foreground">{u.requests} calls · ${u.cost_usd.toFixed(2)}</span></div>)}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
