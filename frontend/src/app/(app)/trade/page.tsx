"use client";
import * as React from "react";
import Link from "next/link";
import { Empty, ErrorNote, PageHeader, Pager } from "@/components/common";
import { countryName, useApp, useFetch } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Input, Label } from "@/components/ui/input";
import { MultiSelect } from "@/components/ui/multi-select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Shipment } from "@/lib/types";
import { fmtDate, fmtNum, label } from "@/lib/utils";

type Pair = { exporter_name_raw: string; exporter_company_id: string | null; exporter_country: string | null; importer_name_raw: string;
  importer_company_id: string | null; importer_country: string | null; shipments: number; first: string | null; last: string | null; weight_kg: number };
type Stat = { reporter: string; partner: string; partner_name: string | null; flow: string; hs_code: string; hs_description: string | null;
  period: string; value_usd: number | null; net_weight_kg: number | null; quantity: number | null; quantity_unit: string | null };

function CompanyLink({ id, name }: { id: string | null; name: string | null }) {
  if (!name) return <span className="text-muted-foreground">—</span>;
  return id ? <Link href={`/companies/${id}`} className="hover:text-primary">{name}</Link> : <span>{name}</span>;
}

export default function TradePage() {
  const { meta } = useApp();
  const [f, setF] = React.useState({ importer: "", exporter: "", hs_code: "", date_from: "", date_to: "", min_qty: "", max_qty: "", q: "" });
  const [country, setCountry] = React.useState<string[]>([]);
  const [material, setMaterial] = React.useState<string[]>([]);
  const [page, setPage] = React.useState(1);
  const [d, setD] = React.useState(f);
  React.useEffect(() => { const t = setTimeout(() => { setD(f); setPage(1); }, 350); return () => clearTimeout(t); }, [f]);
  const ships = useFetch<{ total: number; items: Shipment[] }>("/shipments", { ...d, country, material, page, page_size: 50 });
  const pairs = useFetch<Pair[]>("/shipments/relationships", { country, material });
  const stats = useFetch<Stat[]>("/trade-stats", {});
  const inp = (k: keyof typeof f, ph: string, type = "text") => <Input type={type} placeholder={ph} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} />;
  return (
    <>
      <PageHeader title="Trade intelligence" description="Shipment records from permitted trade-data exports/APIs, and official country-level statistics (UN Comtrade, US Census) by HS code." />
      <div className="mb-4 grid grid-cols-1 gap-2 rounded-lg border bg-card p-3 sm:grid-cols-2 lg:grid-cols-5">
        {inp("importer", "Importer / consignee")}{inp("exporter", "Exporter / shipper")}
        <MultiSelect placeholder="Country" value={country} onChange={(v) => { setCountry(v); setPage(1); }} options={(meta?.countries ?? []).map((c) => ({ value: c.code, label: c.name }))} />
        <MultiSelect placeholder="Material" value={material} onChange={(v) => { setMaterial(v); setPage(1); }} options={(meta?.materials ?? []).map((m) => ({ value: m.code }))} />
        {inp("hs_code", "HS code prefix (e.g. 3901)")}
        <div className="flex flex-col gap-0.5"><Label>From</Label>{inp("date_from", "", "date")}</div>
        <div className="flex flex-col gap-0.5"><Label>To</Label>{inp("date_to", "", "date")}</div>
        <div className="flex flex-col gap-0.5"><Label>Min qty / kg</Label>{inp("min_qty", "", "number")}</div>
        <div className="flex flex-col gap-0.5"><Label>Max qty / kg</Label>{inp("max_qty", "", "number")}</div>
        <div className="flex flex-col gap-0.5"><Label>Description</Label>{inp("q", "contains…")}</div>
      </div>
      <Tabs defaultValue="shipments">
        <TabsList>
          <TabsTrigger value="shipments">Shipments ({ships.data?.total ?? 0})</TabsTrigger>
          <TabsTrigger value="pairs">Supplier → buyer relationships</TabsTrigger>
          <TabsTrigger value="stats">Country statistics ({stats.data?.length ?? 0})</TabsTrigger>
        </TabsList>
        <TabsContent value="shipments">
          <ErrorNote error={ships.error} />
          {ships.data?.total === 0 ? <Empty title="No shipment records">Import a CSV/XLSX export from ImportYeti, Volza, Panjiva or TradeData.Pro in Data sources.</Empty> : (
            <div className="rounded-lg border bg-card"><Table>
              <THead><TR><TH>Date</TH><TH>Exporter</TH><TH>Importer</TH><TH>HS</TH><TH>Material</TH><TH>Description</TH><TH>Weight kg</TH><TH>Value</TH><TH>Source</TH></TR></THead>
              <TBody>{ships.data?.items.map((s) => (
                <TR key={s.id}>
                  <TD className="whitespace-nowrap">{fmtDate(s.shipment_date)}</TD>
                  <TD className="min-w-40"><CompanyLink id={s.exporter_company_id} name={s.exporter_name} /><span className="block text-xs text-muted-foreground">{countryName(meta, s.exporter_country)}</span></TD>
                  <TD className="min-w-40"><CompanyLink id={s.importer_company_id} name={s.importer_name} /><span className="block text-xs text-muted-foreground">{countryName(meta, s.importer_country)}</span></TD>
                  <TD>{s.hs_code ?? "—"}</TD>
                  <TD>{s.material ? <Badge variant="primary" title={`inferred from ${s.material_inference}`}>{label(s.material)}{s.material_inference === "ambiguous_hs" ? "*" : ""}</Badge> : "—"}{s.grade_category && <span className="block text-xs text-muted-foreground">{label(s.grade_category)}</span>}</TD>
                  <TD className="max-w-72 text-xs">{s.product_description}</TD>
                  <TD className="tabular-nums">{fmtNum(s.weight_kg)}</TD>
                  <TD className="whitespace-nowrap tabular-nums">{s.value != null ? `${s.currency ?? ""} ${fmtNum(s.value)}` : "—"}</TD>
                  <TD className="text-xs text-muted-foreground">{s.source}</TD>
                </TR>))}</TBody>
            </Table>{ships.data && <Pager page={page} pageSize={50} total={ships.data.total} onPage={setPage} />}</div>
          )}
          <p className="mt-2 text-xs text-muted-foreground">* HS 3901.10 covers LDPE and some LLDPE: material inferred from HS only. Off-grade / near-prime have no customs code; they are detected from descriptions only.</p>
        </TabsContent>
        <TabsContent value="pairs">
          {!pairs.data?.length ? <Empty title="No supplier–buyer relationships yet">Relationships are derived from shipment records only.</Empty> : (
            <div className="rounded-lg border bg-card"><Table>
              <THead><TR><TH>Supplier (exporter)</TH><TH>Buyer (importer)</TH><TH>Shipments</TH><TH>First</TH><TH>Last</TH><TH>Total kg</TH></TR></THead>
              <TBody>{pairs.data.map((p, i) => (
                <TR key={i}>
                  <TD><CompanyLink id={p.exporter_company_id} name={p.exporter_name_raw} /><span className="block text-xs text-muted-foreground">{countryName(meta, p.exporter_country)}</span></TD>
                  <TD><CompanyLink id={p.importer_company_id} name={p.importer_name_raw} /><span className="block text-xs text-muted-foreground">{countryName(meta, p.importer_country)}</span></TD>
                  <TD className="tabular-nums">{p.shipments}</TD><TD>{fmtDate(p.first)}</TD><TD>{fmtDate(p.last)}</TD><TD className="tabular-nums">{fmtNum(p.weight_kg)}</TD>
                </TR>))}</TBody>
            </Table></div>
          )}
        </TabsContent>
        <TabsContent value="stats">
          {!stats.data?.length ? <Empty title="No official statistics collected yet">Run the UN Comtrade or US Census connector in Data sources (free, no company names; market sizing only).</Empty> : (
            <div className="rounded-lg border bg-card"><Table>
              <THead><TR><TH>Reporter</TH><TH>Flow</TH><TH>Partner</TH><TH>HS</TH><TH>Period</TH><TH>Value USD</TH><TH>Net kg</TH></TR></THead>
              <TBody>{stats.data.map((s, i) => (
                <TR key={i}><TD>{countryName(meta, s.reporter)}</TD><TD>{label(s.flow)}</TD><TD>{s.partner === "W" ? "World" : s.partner_name ?? countryName(meta, s.partner)}</TD>
                  <TD title={s.hs_description ?? ""}>{s.hs_code}</TD><TD>{s.period}</TD><TD className="tabular-nums">{fmtNum(s.value_usd)}</TD><TD className="tabular-nums">{fmtNum(s.net_weight_kg)}</TD></TR>))}</TBody>
            </Table></div>
          )}
        </TabsContent>
      </Tabs>
    </>
  );
}
