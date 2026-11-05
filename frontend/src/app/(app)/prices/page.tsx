"use client";
import * as React from "react";
import { ArrowDownRight, ArrowUpRight, Bell, ExternalLink, Minus, Plus, RefreshCw, Trash2, Upload } from "lucide-react";
import { Empty, ErrorNote, PageHeader } from "@/components/common";
import { LineChart, SERIES_COLORS, Sparkline } from "@/components/price-chart";
import { countryName, useApp, useFetch } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { MultiSelect } from "@/components/ui/multi-select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { cn, fmtDate, label } from "@/lib/utils";

type Point = { id: number; observed_at: string; price: number; low: number | null; high: number | null; volume: number | null;
  open_interest: number | null; contract: string | null; is_provisional: boolean; origin: string; source_url: string | null;
  note: string | null; normalized?: number | null };
type Series = { id: number; key: string; name: string; material: string | null; grade: string | null; country_code: string | null;
  location: string | null; price_type: string; currency: string | null; unit: string; incoterm: string | null; frequency: string;
  source_key: string | null; source_name: string | null; source_status: string | null; external_code: string | null;
  config: Record<string, unknown>; is_active: boolean; notes: string | null };
type BoardRow = Series & { latest: Point | null; previous: number | null; change_pct: number | null; change_1w_pct: number | null;
  change_1m_pct: number | null; change_1y_pct: number | null; normalized: number | null; normalized_unit: string | null;
  is_stale: boolean | null; age_days: number | null; spark: { t: string; v: number }[]; points: number };
type Fx = { currency: string; per_usd: number; rate_date: string | null; source: string };
type Board = { currency: string; unit: string; generated_at: string; last_collected_at: string | null; items: BoardRow[]; fx: Fx[] };
type Compare = { series: (Series & { data: { t: string; v: number }[] })[]; skipped: { key: string; reason: string }[] };
type Rule = { id: number; series_id: number; series_name: string | null; condition: string; threshold: number; is_active: boolean; last_triggered_at: string | null };
type PriceMeta = { price_types: string[]; frequencies: string[]; units: string[]; alert_conditions: string[]; sources: { key: string; name: string; status: string; enabled: boolean }[] };

const DISPLAY = [
  { v: "USD:t", l: "USD / tonne" }, { v: "INR:kg", l: "INR / kg" }, { v: "CNY:t", l: "CNY / tonne" },
  { v: "EUR:t", l: "EUR / tonne" }, { v: "USD:lb", l: "USD / lb" }, { v: "INR:t", l: "INR / tonne" },
];
const RANGES = [{ v: 90, l: "3M" }, { v: 180, l: "6M" }, { v: 365, l: "1Y" }, { v: 1095, l: "3Y" }, { v: 1825, l: "5Y" }];
const TYPE_LABEL: Record<string, string> = { futures: "Futures", spot: "Spot", contract: "Contract", producer_list: "Producer list",
  assessment: "Assessment", index: "Index", feedstock: "Feedstock" };
const GROUP_ORDER = ["IN", "CN", "US"];

function fmtPrice(v: number | null | undefined) {
  if (v === null || v === undefined) return "—";
  const a = Math.abs(v);
  return v.toLocaleString(undefined, { minimumFractionDigits: a < 10 ? 2 : 0, maximumFractionDigits: a < 10 ? 3 : a < 1000 ? 1 : 0 });
}
function unitLabel(s: { currency: string | null; unit: string }) {
  return s.unit === "index" ? "index" : `${s.currency ?? ""}/${s.unit}`;
}
function isoDaysAgo(n: number) { return new Date(Date.now() - n * 864e5).toISOString().slice(0, 10); }

function Change({ v, small }: { v: number | null; small?: boolean }) {
  if (v === null || v === undefined) return <span className="text-muted-foreground">—</span>;
  const Icon = v > 0 ? ArrowUpRight : v < 0 ? ArrowDownRight : Minus;
  return (
    <span className={cn("inline-flex items-center gap-0.5 tabular-nums", small ? "text-xs" : "text-sm", v > 0 ? "text-good" : v < 0 ? "text-bad" : "text-muted-foreground")}
      aria-label={`${v > 0 ? "up" : v < 0 ? "down" : "unchanged"} ${Math.abs(v)} percent`}>
      <Icon className="size-3.5" />{v > 0 ? "+" : ""}{v.toFixed(2)}%
    </span>
  );
}

function Freshness({ r }: { r: BoardRow }) {
  if (!r.latest) return <Badge variant="outline">No data yet</Badge>;
  return (
    <span className="whitespace-nowrap text-xs">
      {fmtDate(r.latest.observed_at)}
      {r.is_stale ? <Badge variant="warn" className="ml-1" title={`Latest point is ${r.age_days} days old for a ${r.frequency} series`}>Stale</Badge>
        : r.latest.is_provisional ? <Badge variant="outline" className="ml-1">Prelim.</Badge> : null}
    </span>
  );
}

// ------------------------------------------------------------------ board
function BoardTable({ rows, onOpen }: { rows: BoardRow[]; onOpen: (r: BoardRow) => void }) {
  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <Table>
        <THead><TR><TH>Series</TH><TH className="text-right">Latest</TH><TH className="text-right">Display</TH><TH>Last move</TH><TH>1W</TH><TH>1M</TH><TH>1Y</TH><TH>Trend</TH><TH>As of</TH></TR></THead>
        <TBody>{rows.map((r) => (
          <TR key={r.id} className="cursor-pointer" onClick={() => onOpen(r)}>
            <TD className="min-w-56">
              <span className="font-medium">{r.name}</span>
              <span className="mt-0.5 flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                <Badge variant={r.price_type === "futures" ? "primary" : "outline"}>{TYPE_LABEL[r.price_type] ?? r.price_type}</Badge>
                {r.material && <Badge>{label(r.material)}</Badge>}
                {[r.grade, r.location, r.incoterm].filter(Boolean).join(" · ")}
              </span>
            </TD>
            <TD className="whitespace-nowrap text-right tabular-nums">
              <span className="font-semibold">{fmtPrice(r.latest?.price)}</span>
              <span className="block text-[11px] text-muted-foreground">{unitLabel(r)}</span>
            </TD>
            <TD className="whitespace-nowrap text-right tabular-nums">
              {r.normalized !== null ? <>{fmtPrice(r.normalized)}<span className="block text-[11px] text-muted-foreground">{r.normalized_unit}</span></>
                : <span className="text-xs text-muted-foreground" title={r.unit === "index" ? "An index has no currency/unit" : "No FX rate or not a mass unit"}>n/a</span>}
            </TD>
            <TD><Change v={r.change_pct} /></TD>
            <TD><Change v={r.change_1w_pct} small /></TD>
            <TD><Change v={r.change_1m_pct} small /></TD>
            <TD><Change v={r.change_1y_pct} small /></TD>
            <TD><Sparkline data={r.spark} /></TD>
            <TD><Freshness r={r} /><span className="block text-[11px] text-muted-foreground">{r.source_name?.split(" (")[0].split(":")[0] ?? "—"}</span></TD>
          </TR>
        ))}</TBody>
      </Table>
    </div>
  );
}

// ------------------------------------------------------------------ series detail
function SeriesDialog({ row, currency, unit, canEdit, onClose, onChanged }: { row: BoardRow; currency: string; unit: string; canEdit: boolean; onClose: () => void; onChanged: () => void }) {
  const [range, setRange] = React.useState(365);
  const hist = useFetch<{ series: Series; normalized_unit: string | null; points: Point[] }>(`/prices/series/${row.id}/history`,
    { date_from: isoDaysAgo(range), currency: row.unit === "index" ? undefined : currency, unit: row.unit === "index" ? undefined : unit });
  const [showNorm, setShowNorm] = React.useState(false);
  const [form, setForm] = React.useState({ observed_at: new Date().toISOString().slice(0, 10), price: "", low: "", high: "", note: "", source_url: "" });
  const [alert, setAlert] = React.useState({ condition: "change_pct", threshold: "" });
  const [err, setErr] = React.useState<string | null>(null);
  const [msg, setMsg] = React.useState<string | null>(null);
  const pts = hist.data?.points ?? [];
  const canNorm = !!hist.data?.normalized_unit && pts.some((p) => p.normalized != null);
  const line = { id: row.id, label: row.name, color: SERIES_COLORS[0],
    data: pts.map((p) => ({ t: p.observed_at, v: (showNorm && canNorm ? p.normalized : p.price) as number })).filter((d) => d.v != null) };

  const addPoint = async () => {
    setErr(null); setMsg(null);
    try {
      const num = (s: string) => (s.trim() ? Number(s) : null);
      await api(`/prices/series/${row.id}/points`, { method: "POST", body: JSON.stringify({ observed_at: form.observed_at, price: Number(form.price),
        low: num(form.low), high: num(form.high), note: form.note || null, source_url: form.source_url || null }) });
      setMsg("Price saved."); setForm({ ...form, price: "", low: "", high: "" });
      hist.reload(); onChanged();
    } catch (e) { setErr((e as Error).message); }
  };
  const addAlert = async () => {
    setErr(null); setMsg(null);
    try {
      await api("/prices/alerts", { method: "POST", body: JSON.stringify({ series_id: row.id, condition: alert.condition, threshold: Number(alert.threshold) }) });
      setMsg("Alert rule created — you will see it under the bell icon (and your webhook, if configured)."); setAlert({ ...alert, threshold: "" });
    } catch (e) { setErr((e as Error).message); }
  };
  const del = async (id: number) => {
    try { await api(`/prices/points/${id}`, { method: "DELETE" }); hist.reload(); onChanged(); } catch (e) { setErr((e as Error).message); }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={row.name} className="max-w-4xl"
        description={[row.country_code ? `${row.country_code}` : null, TYPE_LABEL[row.price_type], unitLabel(row), row.frequency, row.source_name].filter(Boolean).join(" · ")}>
        {row.notes && <p className="mb-3 text-xs text-muted-foreground">{row.notes}</p>}
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <div className="flex rounded-md border p-0.5">{RANGES.map((r) => (
            <button key={r.v} onClick={() => setRange(r.v)} className={cn("rounded px-2 py-1 text-xs", range === r.v ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-muted")}>{r.l}</button>))}
          </div>
          {canNorm && (
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <input type="checkbox" checked={showNorm} onChange={(e) => setShowNorm(e.target.checked)} /> Show in {hist.data?.normalized_unit}
            </label>
          )}
          <span className="ml-auto text-xs text-muted-foreground">{pts.length} points</span>
        </div>
        <ErrorNote error={hist.error} />
        {pts.length ? <LineChart lines={[line]} unit={showNorm && canNorm ? hist.data!.normalized_unit! : unitLabel(row)} height={240} />
          : <Empty title="No prices in this range">{row.source_key === "price_import" ? "Add a price below or import a CSV." : row.source_status !== "active" ? `Source status: ${label(row.source_status)}. See Data sources.` : "Run Refresh now to collect."}</Empty>}

        {canEdit && (
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <div className="rounded-lg border p-3">
              <p className="mb-2 text-sm font-medium">Add a price</p>
              <div className="grid grid-cols-2 gap-2">
                <div className="flex flex-col gap-0.5"><Label>Date</Label><Input type="date" value={form.observed_at} onChange={(e) => setForm({ ...form, observed_at: e.target.value })} /></div>
                <div className="flex flex-col gap-0.5"><Label>Price ({unitLabel(row)})</Label><Input type="number" step="any" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} /></div>
                <div className="flex flex-col gap-0.5"><Label>Low (optional)</Label><Input type="number" step="any" value={form.low} onChange={(e) => setForm({ ...form, low: e.target.value })} /></div>
                <div className="flex flex-col gap-0.5"><Label>High (optional)</Label><Input type="number" step="any" value={form.high} onChange={(e) => setForm({ ...form, high: e.target.value })} /></div>
              </div>
              <div className="mt-2 flex flex-col gap-0.5"><Label>Basis / source note</Label><Textarea className="min-h-14" placeholder="e.g. Reliance circular 12 Oct, ex-Mumbai, excl. GST" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></div>
              <div className="mt-2 flex flex-col gap-0.5"><Label>Source URL (optional)</Label><Input value={form.source_url} onChange={(e) => setForm({ ...form, source_url: e.target.value })} /></div>
              <Button className="mt-2" size="sm" disabled={!form.price || Number(form.price) <= 0} onClick={addPoint}><Plus /> Save price</Button>
            </div>
            <div className="rounded-lg border p-3">
              <p className="mb-2 text-sm font-medium">Alert me when…</p>
              <div className="grid grid-cols-2 gap-2">
                <NativeSelect value={alert.condition} onChange={(e) => setAlert({ ...alert, condition: e.target.value })}>
                  <option value="change_pct">moves by ≥ X %</option><option value="above">rises above</option><option value="below">falls below</option>
                </NativeSelect>
                <Input type="number" step="any" placeholder={alert.condition === "change_pct" ? "%" : unitLabel(row)} value={alert.threshold} onChange={(e) => setAlert({ ...alert, threshold: e.target.value })} />
              </div>
              <Button className="mt-2" size="sm" variant="outline" disabled={!alert.threshold} onClick={addAlert}><Bell /> Create alert</Button>
              <p className="mt-2 text-xs text-muted-foreground">Checked whenever a new latest price arrives (connector, import or manual entry). Back-filled history never alerts.</p>
            </div>
          </div>
        )}
        {(err || msg) && <p className={cn("mt-2 text-sm", err ? "text-bad" : "text-good")}>{err ?? msg}</p>}

        {pts.length > 0 && (
          <div className="mt-4 max-h-72 overflow-y-auto rounded-lg border">
            <Table>
              <THead><TR><TH>Date</TH><TH className="text-right">Price</TH><TH className="text-right">Low–High</TH><TH>Detail</TH><TH>Origin</TH><TH /></TR></THead>
              <TBody>{[...pts].reverse().map((p) => (
                <TR key={p.id}>
                  <TD className="whitespace-nowrap">{fmtDate(p.observed_at)}</TD>
                  <TD className="text-right tabular-nums">{fmtPrice(p.price)}</TD>
                  <TD className="whitespace-nowrap text-right tabular-nums text-xs">{p.low || p.high ? `${fmtPrice(p.low)} – ${fmtPrice(p.high)}` : "—"}</TD>
                  <TD className="max-w-64 text-xs text-muted-foreground">{[p.contract, p.note].filter(Boolean).join(" · ") || "—"}
                    {p.source_url && <a href={p.source_url} target="_blank" rel="noreferrer" className="ml-1 inline-flex text-primary" onClick={(e) => e.stopPropagation()}><ExternalLink className="size-3" /></a>}</TD>
                  <TD className="text-xs">{label(p.origin)}</TD>
                  <TD>{canEdit && p.origin !== "connector" && <button aria-label="Delete price" className="text-muted-foreground hover:text-bad" onClick={() => del(p.id)}><Trash2 className="size-3.5" /></button>}</TD>
                </TR>))}</TBody>
            </Table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ add series / import
function AddSeriesDialog({ pm, onDone }: { pm: PriceMeta | null; onDone: () => void }) {
  const { meta } = useApp();
  const [open, setOpen] = React.useState(false);
  const blank = { key: "", name: "", material: "LLDPE", grade: "", country_code: "IN", location: "", price_type: "spot", currency: "INR", unit: "kg",
    incoterm: "", frequency: "weekly", source_key: "price_import", feed_url: "", notes: "" };
  const [f, setF] = React.useState(blank);
  const [err, setErr] = React.useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  const save = async () => {
    setErr(null);
    try {
      const { feed_url, ...rest } = f;
      await api("/prices/series", { method: "POST", body: JSON.stringify({ ...rest, key: f.key || f.name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 80),
        material: f.material || null, grade: f.grade || null, country_code: f.country_code || null, location: f.location || null, incoterm: f.incoterm || null,
        currency: f.unit === "index" ? null : f.currency, notes: f.notes || null, config: feed_url ? { feed_url } : {} }) });
      setOpen(false); setF(blank); onDone();
    } catch (e) { setErr((e as Error).message); }
  };
  const fld = (l: string, el: React.ReactNode) => <div className="flex flex-col gap-0.5"><Label>{l}</Label>{el}</div>;
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button variant="outline" onClick={() => setOpen(true)}><Plus /> Add series</Button>
      <DialogContent title="Track a new price series" description="One material, one market and one price basis (e.g. India HDPE film, producer list price, INR/kg).">
        <div className="grid grid-cols-2 gap-2">
          <div className="col-span-2">{fld("Name", <Input value={f.name} onChange={set("name")} placeholder="Vietnam HDPE film, CFR Ho Chi Minh" />)}</div>
          {fld("Material", <NativeSelect value={f.material} onChange={set("material")}><option value="">— (index / feedstock)</option>{(meta?.materials ?? []).map((m) => <option key={m.code} value={m.code}>{label(m.code)}</option>)}</NativeSelect>)}
          {fld("Grade", <Input value={f.grade} onChange={set("grade")} placeholder="film, raffia, injection…" />)}
          {fld("Country", <NativeSelect value={f.country_code} onChange={set("country_code")}><option value="">— (global)</option>{(meta?.countries ?? []).map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}</NativeSelect>)}
          {fld("Location / basis", <Input value={f.location} onChange={set("location")} placeholder="ex-Mumbai, CFR China, FAS Houston" />)}
          {fld("Price type", <NativeSelect value={f.price_type} onChange={set("price_type")}>{(pm?.price_types ?? []).map((t) => <option key={t} value={t}>{TYPE_LABEL[t] ?? t}</option>)}</NativeSelect>)}
          {fld("Frequency", <NativeSelect value={f.frequency} onChange={set("frequency")}>{(pm?.frequencies ?? []).map((t) => <option key={t} value={t}>{label(t)}</option>)}</NativeSelect>)}
          {fld("Currency", <Input value={f.currency} maxLength={3} onChange={set("currency")} disabled={f.unit === "index"} />)}
          {fld("Unit", <NativeSelect value={f.unit} onChange={set("unit")}>{(pm?.units ?? []).map((u) => <option key={u} value={u}>{u === "t" ? "tonne" : u}</option>)}</NativeSelect>)}
          {fld("Incoterm", <Input value={f.incoterm} onChange={set("incoterm")} placeholder="CFR, FOB, FAS, ex-works…" />)}
          {fld("Data source", <NativeSelect value={f.source_key} onChange={set("source_key")}>
            <option value="price_import">Manual entry / import</option><option value="price_feed">Feed URL (CSV / JSON)</option>
          </NativeSelect>)}
          {f.source_key === "price_feed" && <div className="col-span-2">{fld("Feed URL", <Input value={f.feed_url} onChange={set("feed_url")} placeholder="https://… (CSV with date,price columns). Secrets: ${ENV:VAR_NAME}" />)}</div>}
          <div className="col-span-2">{fld("Notes", <Textarea className="min-h-14" value={f.notes} onChange={set("notes")} />)}</div>
        </div>
        {err && <p className="mt-2 text-sm text-bad">{err}</p>}
        <Button className="mt-3" disabled={f.name.length < 3} onClick={save}>Create series</Button>
      </DialogContent>
    </Dialog>
  );
}

function ImportDialog({ series, onDone }: { series: BoardRow[]; onDone: () => void }) {
  const [open, setOpen] = React.useState(false);
  const [file, setFile] = React.useState<File | null>(null);
  const [key, setKey] = React.useState("");
  const [res, setRes] = React.useState<{ rows: number; created: number; updated: number; failed: number; errors: { row: number; error: string }[] } | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const go = async () => {
    if (!file) return;
    setErr(null);
    const fd = new FormData();
    fd.append("file", file);
    if (key) fd.append("series_key", key);
    try { setRes(await api("/prices/import", { method: "POST", body: fd })); onDone(); } catch (e) { setErr((e as Error).message); }
  };
  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) setRes(null); }}>
      <Button variant="outline" onClick={() => setOpen(true)}><Upload /> Import CSV</Button>
      <DialogContent title="Import price history" description="CSV or Excel with columns: series_key, date, price — optional low, high, note, source_url. Use only data you are permitted to store.">
        <pre className="mb-3 overflow-x-auto rounded bg-muted p-2 text-[11px]">series_key,date,price,note{"\n"}in_lldpe_film_list,2026-10-12,104.5,ex-Mumbai excl. GST</pre>
        <div className="flex flex-col gap-2">
          <Input type="file" accept=".csv,.xlsx,.xlsm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <NativeSelect value={key} onChange={(e) => setKey(e.target.value)}>
            <option value="">File has a series_key column</option>
            {series.map((s) => <option key={s.key} value={s.key}>All rows → {s.name}</option>)}
          </NativeSelect>
          <Button disabled={!file} onClick={go}>Import</Button>
        </div>
        {err && <p className="mt-2 text-sm text-bad">{err}</p>}
        {res && (
          <div className="mt-3 text-sm">
            <p>{res.rows} rows · <span className="text-good">{res.created} new</span> · {res.updated} updated · <span className={res.failed ? "text-bad" : ""}>{res.failed} failed</span></p>
            {res.errors.slice(0, 8).map((e) => <p key={e.row} className="text-xs text-muted-foreground">Row {e.row}: {e.error}</p>)}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ compare
function CompareTab({ currency, unit, materials }: { currency: string; unit: string; materials: string[] }) {
  const [material, setMaterial] = React.useState("LLDPE");
  const [range, setRange] = React.useState(365);
  const [asTable, setAsTable] = React.useState(false);
  const { data, error } = useFetch<Compare>("/prices/compare", { material, currency, unit, date_from: isoDaysAgo(range) });
  const shown = (data?.series ?? []).slice(0, 8);
  // colour follows the entity: slot by position in this material's full (id-ordered) series list
  const order = [...(data?.series ?? [])].sort((a, b) => a.id - b.id).map((s) => s.id);
  const lines = shown.map((s) => ({ id: s.id, label: `${s.country_code ?? "—"} · ${s.name.replace(/^(India|China|US|USA)\s+/, "")}`, color: SERIES_COLORS[order.indexOf(s.id) % 8], data: s.data }));
  const u = `${currency}/${unit}`;
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <NativeSelect className="w-40" value={material} onChange={(e) => setMaterial(e.target.value)}>{materials.map((m) => <option key={m} value={m}>{label(m)}</option>)}</NativeSelect>
        <div className="flex rounded-md border p-0.5">{RANGES.map((r) => (
          <button key={r.v} onClick={() => setRange(r.v)} className={cn("rounded px-2 py-1 text-xs", range === r.v ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-muted")}>{r.l}</button>))}
        </div>
        <Button size="sm" variant="ghost" onClick={() => setAsTable(!asTable)}>{asTable ? "Show chart" : "Show table"}</Button>
        <span className="ml-auto text-xs text-muted-foreground">All markets converted to {u} at each day&apos;s FX rate</span>
      </div>
      <ErrorNote error={error} />
      {!shown.length ? <Empty title={`No ${label(material)} prices in this range yet`}>Add prices to the India / China / US series on the Board tab, import a CSV, or enable the DCE connector for China futures.</Empty>
        : asTable ? (
          <div className="max-h-96 overflow-auto"><Table>
            <THead><TR><TH>Series</TH><TH>Date</TH><TH className="text-right">{u}</TH></TR></THead>
            <TBody>{shown.flatMap((s) => [...s.data].reverse().slice(0, 60).map((d) => (
              <TR key={`${s.id}-${d.t}`}><TD className="text-xs">{s.name}</TD><TD className="text-xs">{fmtDate(d.t)}</TD><TD className="text-right tabular-nums">{fmtPrice(d.v)}</TD></TR>)))}</TBody>
          </Table></div>
        ) : <LineChart lines={lines} unit={u} height={320} />}
      {(data?.series.length ?? 0) > 8 && <p className="mt-2 text-xs text-muted-foreground">Showing the first 8 of {data!.series.length} series — narrow with the country filter.</p>}
      {data?.skipped.map((s) => <p key={s.key} className="mt-1 text-xs text-warn">{s.key}: {s.reason} — add the rate on the FX tab.</p>)}
      <p className="mt-3 text-xs text-muted-foreground">Bases differ (futures incl. VAT, producer list prices, CFR import prices): compare direction and spreads, not just levels. Indices are excluded because they have no currency.</p>
    </div>
  );
}

// ------------------------------------------------------------------ page
export default function PricesPage() {
  const { me, meta } = useApp();
  const canEdit = me?.role === "admin" || me?.role === "analyst";
  const [display, setDisplay] = React.useState(() => {
    try { const d = localStorage.getItem("pti_price_display"); if (d && DISPLAY.some((o) => o.v === d)) return d; } catch { /* ignore */ }
    return "USD:t";
  });
  const [currency, unit] = display.split(":");
  const [material, setMaterial] = React.useState<string[]>([]);
  const [country, setCountry] = React.useState<string[]>([]);
  const [live, setLive] = React.useState(true);
  const board = useFetch<Board>("/prices/board", { currency, unit, material, country });
  const pm = useFetch<PriceMeta>("/prices/meta", {});
  const rules = useFetch<Rule[]>("/prices/alerts", {});
  const [open, setOpen] = React.useState<BoardRow | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);
  const [refreshMsg, setRefreshMsg] = React.useState<string | null>(null);
  const [fxForm, setFxForm] = React.useState({ currency: "", per_usd: "", rate_date: new Date().toISOString().slice(0, 10) });
  const reloadBoard = board.reload;
  const reloadRef = React.useRef(reloadBoard);
  React.useEffect(() => { reloadRef.current = reloadBoard; });

  React.useEffect(() => {
    if (!live) return;
    const t = setInterval(() => { if (document.visibilityState === "visible") reloadRef.current(); }, 60_000);
    return () => clearInterval(t);
  }, [live]);

  const changeDisplay = (v: string) => { setDisplay(v); try { localStorage.setItem("pti_price_display", v); } catch { /* ignore */ } };
  const refresh = async () => {
    setRefreshing(true); setRefreshMsg(null);
    try {
      const r = await api<{ jobs: { source: string; status: string; reason?: string }[] }>("/prices/refresh", { method: "POST" });
      setRefreshMsg(r.jobs.map((j) => `${j.source}: ${j.status}${j.reason ? ` (${j.reason})` : ""}`).join(" · ") + " — the worker collects queued jobs within a minute.");
      setTimeout(reloadBoard, 15_000);
    } catch (e) { setRefreshMsg((e as Error).message); } finally { setRefreshing(false); }
  };

  const items = board.data?.items ?? [];
  const withData = items.filter((r) => r.latest);
  const empty = items.filter((r) => !r.latest);
  const groups = new Map<string, BoardRow[]>();
  for (const r of withData) { const k = r.country_code ?? "GLOBAL"; groups.set(k, [...(groups.get(k) ?? []), r]); }
  const groupKeys = [...groups.keys()].sort((a, b) => (GROUP_ORDER.indexOf(a) + 1 || 99) - (GROUP_ORDER.indexOf(b) + 1 || 99) || a.localeCompare(b));
  const pricedMaterials = Array.from(new Set(items.filter((r) => r.material && r.unit !== "index").map((r) => r.material!)));

  return (
    <>
      <PageHeader title="Market prices"
        description="Polymer price benchmarks across India, China, the USA and other markets: exchange futures, producer list prices, import assessments, official indices and feedstocks. Every price is stored as published, with its source; conversions use the FX rate of the price date."
        actions={canEdit ? <>
          <Button variant="outline" onClick={refresh} disabled={refreshing}><RefreshCw className={cn(refreshing && "animate-spin")} /> Refresh now</Button>
          <ImportDialog series={items} onDone={reloadBoard} />
          <AddSeriesDialog pm={pm.data} onDone={reloadBoard} />
        </> : undefined} />

      <div className="mb-4 grid grid-cols-1 gap-2 rounded-lg border bg-card p-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="flex flex-col gap-0.5"><Label>Display prices in</Label>
          <NativeSelect value={display} onChange={(e) => changeDisplay(e.target.value)}>{DISPLAY.map((d) => <option key={d.v} value={d.v}>{d.l}</option>)}</NativeSelect></div>
        <div className="flex flex-col gap-0.5"><Label>Material</Label>
          <MultiSelect placeholder="All polymers" value={material} onChange={setMaterial} options={(meta?.materials ?? []).map((m) => ({ value: m.code, label: label(m.code) }))} /></div>
        <div className="flex flex-col gap-0.5"><Label>Market</Label>
          <MultiSelect placeholder="All countries" value={country} onChange={setCountry} options={(meta?.countries ?? []).map((c) => ({ value: c.code, label: c.name }))} /></div>
        <div className="flex flex-col justify-end gap-1 text-xs text-muted-foreground">
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> Auto-refresh every 60 s</label>
          <span>Board updated {board.data ? fmtDate(board.data.generated_at, true) : "…"} · last collection {fmtDate(board.data?.last_collected_at, true)}</span>
        </div>
      </div>
      {refreshMsg && <p className="mb-3 rounded-md border bg-card px-3 py-2 text-xs text-muted-foreground">{refreshMsg}</p>}
      <ErrorNote error={board.error} />

      <Tabs defaultValue="board">
        <TabsList>
          <TabsTrigger value="board">Price board ({withData.length})</TabsTrigger>
          <TabsTrigger value="compare">Compare markets</TabsTrigger>
          <TabsTrigger value="alerts">Alerts ({rules.data?.length ?? 0})</TabsTrigger>
          <TabsTrigger value="fx">FX rates</TabsTrigger>
        </TabsList>

        <TabsContent value="board">
          {board.data && !withData.length && (
            <Empty title="No prices collected yet">
              The FRED connector (US resin indices, crude, natural gas, FX) runs automatically every few hours with no key — or click <b>Refresh now</b>.
              China futures need DCE API credentials; India producer prices come from price circulars via manual entry, CSV import or a feed URL.
            </Empty>
          )}
          {groupKeys.map((k) => (
            <section key={k} className="mb-5">
              <h2 className="mb-2 text-sm font-semibold">{k === "GLOBAL" ? "Global / feedstock" : countryName(meta, k)}</h2>
              <BoardTable rows={groups.get(k)!} onOpen={setOpen} />
            </section>
          ))}
          {empty.length > 0 && (
            <section className="mb-5">
              <h2 className="mb-1 text-sm font-semibold">Awaiting data ({empty.length})</h2>
              <p className="mb-2 text-xs text-muted-foreground">Tracked series with no prices yet. Nothing is estimated: open a series to add a price, or connect its source.</p>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{empty.map((r) => (
                <button key={r.id} onClick={() => setOpen(r)} className="rounded-lg border bg-card p-3 text-left hover:border-primary/40">
                  <span className="block text-sm font-medium">{r.name}</span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">{countryName(meta, r.country_code)} · {TYPE_LABEL[r.price_type]} · {unitLabel(r)}</span>
                  <span className="mt-1 block text-xs">{r.source_key === "price_import" ? "Manual entry / CSV import" : <>{r.source_name?.split(":")[0]} — <span className="text-warn">{label(r.source_status)}</span></>}</span>
                </button>))}
              </div>
            </section>
          )}
        </TabsContent>

        <TabsContent value="compare">
          <CompareTab currency={currency} unit={unit} materials={pricedMaterials.length ? pricedMaterials : ["LLDPE", "HDPE", "LDPE", "PP", "PVC"]} />
        </TabsContent>

        <TabsContent value="alerts">
          {!rules.data?.length ? <Empty title="No price alerts">Open any series on the board and use “Alert me when…”. Alerts appear under the bell icon and are sent to ALERT_WEBHOOK_URL (e.g. n8n → email / WhatsApp) if configured.</Empty> : (
            <div className="rounded-lg border bg-card"><Table>
              <THead><TR><TH>Series</TH><TH>Condition</TH><TH>Last triggered</TH><TH /></TR></THead>
              <TBody>{rules.data.map((r) => (
                <TR key={r.id}>
                  <TD>{r.series_name}</TD>
                  <TD>{r.condition === "change_pct" ? `moves by ≥ ${r.threshold}%` : `${r.condition === "above" ? "rises above" : "falls below"} ${fmtPrice(r.threshold)}`}</TD>
                  <TD>{fmtDate(r.last_triggered_at, true)}</TD>
                  <TD>{canEdit && <button aria-label="Delete alert" className="text-muted-foreground hover:text-bad" onClick={async () => { await api(`/prices/alerts/${r.id}`, { method: "DELETE" }); rules.reload(); }}><Trash2 className="size-4" /></button>}</TD>
                </TR>))}</TBody>
            </Table></div>
          )}
        </TabsContent>

        <TabsContent value="fx">
          <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
            <div className="rounded-lg border bg-card"><Table>
              <THead><TR><TH>Currency</TH><TH className="text-right">Per 1 USD</TH><TH>Date</TH><TH>Source</TH></TR></THead>
              <TBody>{(board.data?.fx ?? []).map((f) => (
                <TR key={f.currency}><TD className="font-medium">{f.currency}</TD><TD className="text-right tabular-nums">{f.per_usd.toLocaleString(undefined, { maximumFractionDigits: 4 })}</TD>
                  <TD>{f.rate_date ? fmtDate(f.rate_date) : "fixed"}</TD><TD className="text-xs text-muted-foreground">{f.source === "peg" ? "Official peg" : f.source.startsWith("fred:") ? `Federal Reserve H.10 (${f.source.slice(5)})` : label(f.source)}</TD></TR>))}</TBody>
            </Table></div>
            {canEdit && (
              <div className="rounded-lg border bg-card p-3">
                <p className="mb-1 text-sm font-medium">Add a rate</p>
                <p className="mb-2 text-xs text-muted-foreground">For currencies without an automatic feed (e.g. VND). Units of the currency per 1 USD.</p>
                <div className="flex flex-col gap-2">
                  <Input placeholder="Currency (e.g. VND)" maxLength={3} value={fxForm.currency} onChange={(e) => setFxForm({ ...fxForm, currency: e.target.value.toUpperCase() })} />
                  <Input type="number" step="any" placeholder="Per USD" value={fxForm.per_usd} onChange={(e) => setFxForm({ ...fxForm, per_usd: e.target.value })} />
                  <Input type="date" value={fxForm.rate_date} onChange={(e) => setFxForm({ ...fxForm, rate_date: e.target.value })} />
                  <Button size="sm" disabled={fxForm.currency.length !== 3 || !fxForm.per_usd} onClick={async () => {
                    await api("/prices/fx", { method: "POST", body: JSON.stringify({ ...fxForm, per_usd: Number(fxForm.per_usd) }) });
                    setFxForm({ ...fxForm, currency: "", per_usd: "" }); reloadBoard();
                  }}>Save rate</Button>
                </div>
              </div>
            )}
          </div>
        </TabsContent>
      </Tabs>

      {open && <SeriesDialog row={open} currency={currency} unit={unit} canEdit={canEdit} onClose={() => setOpen(null)} onChanged={() => { reloadBoard(); rules.reload(); }} />}
    </>
  );
}
