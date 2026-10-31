"use client";
import * as React from "react";
import Link from "next/link";
import { CalendarClock, Download } from "lucide-react";
import { Empty, ErrorNote, PageHeader, ScoreBadge } from "@/components/common";
import { countryName, useApp, useFetch } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { MultiSelect } from "@/components/ui/multi-select";
import { api, download } from "@/lib/api";
import type { Lead } from "@/lib/types";
import { cn, fmtDate, label } from "@/lib/utils";

function toLocal(v: string | null) {
  if (!v) return "";
  const d = new Date(v);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function LeadCard({ lead, onChange }: { lead: Lead; onChange: () => void }) {
  const { meta } = useApp();
  const [open, setOpen] = React.useState(false);
  const [note, setNote] = React.useState("");
  const [kind, setKind] = React.useState("note");
  const patch = async (body: Record<string, unknown>) => { await api(`/leads/${lead.id}`, { method: "PATCH", body: JSON.stringify(body) }); onChange(); };
  const overdue = lead.next_follow_up_at && new Date(lead.next_follow_up_at) < new Date();
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <Link href={`/companies/${lead.company_id}`} className="font-medium hover:text-primary">{lead.company?.name}</Link>
            <p className="text-xs text-muted-foreground">{countryName(meta, lead.company?.country_code)} · {label(lead.lead_type)} · materials: {lead.interested_materials.join(", ") || "—"}</p>
            <p className="mt-1 text-xs text-muted-foreground">Last contacted {fmtDate(lead.last_contacted_at)} ·{" "}
              <span className={cn(overdue && "font-medium text-bad")}>follow-up {fmtDate(lead.next_follow_up_at, true)}</span></p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <ScoreBadge score={lead.company?.lead_score ?? null} tier={lead.company?.lead_tier ?? null} />
            <NativeSelect className="w-36" value={lead.stage} onChange={(e) => patch({ stage: e.target.value })} aria-label="Stage">
              {meta?.lead_stages.map((s) => <option key={s} value={s}>{label(s)}</option>)}</NativeSelect>
            <NativeSelect className="w-28" value={lead.priority} onChange={(e) => patch({ priority: e.target.value })} aria-label="Priority">
              {meta?.lead_priorities.map((s) => <option key={s} value={s}>{label(s)}</option>)}</NativeSelect>
            <Button size="sm" variant="outline" onClick={() => setOpen(!open)}>{open ? "Close" : "Details"}</Button>
          </div>
        </div>
        {open && (
          <div className="mt-4 grid gap-4 border-t pt-4 lg:grid-cols-2">
            <div className="flex flex-col gap-2">
              <div className="grid gap-2 sm:grid-cols-2">
                <div className="flex flex-col gap-1"><Label>Lead type</Label>
                  <NativeSelect value={lead.lead_type} onChange={(e) => patch({ lead_type: e.target.value })}>{meta?.lead_types.map((s) => <option key={s} value={s}>{label(s)}</option>)}</NativeSelect></div>
                <div className="flex flex-col gap-1"><Label>Interested materials</Label>
                  <MultiSelect placeholder="Materials" value={lead.interested_materials} onChange={(v) => patch({ interested_materials: v })} options={(meta?.materials ?? []).map((m) => ({ value: m.code }))} /></div>
                <div className="flex flex-col gap-1"><Label>Next follow-up</Label>
                  <Input type="datetime-local" defaultValue={toLocal(lead.next_follow_up_at)} onBlur={(e) => patch({ next_follow_up_at: e.target.value ? new Date(e.target.value).toISOString() : null })} /></div>
                <div className="flex flex-col gap-1"><Label>Communication status</Label>
                  <Input defaultValue={lead.communication_status ?? ""} placeholder="e.g. awaiting price list" onBlur={(e) => patch({ communication_status: e.target.value })} /></div>
              </div>
              <div className="flex flex-col gap-1"><Label>Notes</Label><Textarea defaultValue={lead.notes ?? ""} onBlur={(e) => patch({ notes: e.target.value })} /></div>
              <Button size="sm" variant="ghost" className="self-start text-bad" onClick={async () => { if (confirm("Remove this lead?")) { await api(`/leads/${lead.id}`, { method: "DELETE" }); onChange(); } }}>Remove lead</Button>
            </div>
            <div>
              <form className="flex flex-col gap-2" onSubmit={async (e) => { e.preventDefault(); if (!note.trim()) return;
                await api(`/leads/${lead.id}/activities`, { method: "POST", body: JSON.stringify({ activity_type: kind, summary: note }) }); setNote(""); onChange(); }}>
                <div className="flex gap-2">
                  <NativeSelect className="w-32" value={kind} onChange={(e) => setKind(e.target.value)}>{["note", "call", "email", "whatsapp", "meeting"].map((k) => <option key={k} value={k}>{label(k)}</option>)}</NativeSelect>
                  <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Log communication…" />
                  <Button size="sm" type="submit">Log</Button>
                </div>
              </form>
              <ul className="mt-3 flex max-h-64 flex-col divide-y overflow-y-auto">{lead.activities.map((a) => (
                <li key={a.id} className="py-1.5 text-sm"><span className="text-xs text-muted-foreground">{fmtDate(a.created_at, true)} · {label(a.type)}</span><p>{a.summary}</p></li>))}</ul>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function LeadsPage() {
  const { meta } = useApp();
  const [stage, setStage] = React.useState<string[]>([]);
  const [priority, setPriority] = React.useState<string[]>([]);
  const [leadType, setLeadType] = React.useState<string[]>([]);
  const [material, setMaterial] = React.useState<string[]>([]);
  const [due, setDue] = React.useState(false);
  const params = { stage, priority, lead_type: leadType, material, due };
  const { data, error, reload } = useFetch<{ items: Lead[]; stage_counts: Record<string, number> }>("/leads", params);
  return (
    <>
      <PageHeader title="Leads / CRM" description="Saved prospects, their stage, communication log and follow-ups."
        actions={<Button variant="outline" onClick={() => download("/leads/export.csv", { stage, priority, lead_type: leadType, material }, "leads.csv")}><Download /> Export prospects</Button>} />
      <div className="mb-3 flex gap-2 overflow-x-auto pb-1">
        {(meta?.lead_stages ?? []).map((s) => (
          <button key={s} onClick={() => setStage(stage.includes(s) ? stage.filter((x) => x !== s) : [...stage, s])}
            className={cn("min-w-28 rounded-lg border bg-card px-3 py-2 text-left", stage.includes(s) && "border-primary bg-accent")}>
            <p className="text-xs text-muted-foreground">{label(s)}</p><p className="text-lg font-semibold tabular-nums">{data?.stage_counts[s] ?? 0}</p>
          </button>
        ))}
      </div>
      <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
        <MultiSelect placeholder="Priority" value={priority} onChange={setPriority} options={(meta?.lead_priorities ?? []).map((v) => ({ value: v }))} />
        <MultiSelect placeholder="Buyer / supplier" value={leadType} onChange={setLeadType} options={(meta?.lead_types ?? []).map((v) => ({ value: v }))} />
        <MultiSelect placeholder="Interested material" value={material} onChange={setMaterial} options={(meta?.materials ?? []).map((m) => ({ value: m.code }))} />
        <Button variant={due ? "default" : "outline"} onClick={() => setDue(!due)}><CalendarClock /> Follow-ups due</Button>
      </div>
      <ErrorNote error={error} />
      {data && !data.items.length ? <Empty title="No leads here yet">Open any company profile and choose “Save as potential buyer/supplier”.</Empty> : (
        <div className="flex flex-col gap-3">{data?.items.map((l) => <LeadCard key={l.id} lead={l} onChange={reload} />)}</div>
      )}
      {data && <p className="mt-3 text-xs text-muted-foreground"><Badge variant="outline">Tip</Badge> Logging a call/email marks the lead as contacted and moves new leads to “Contacted”.</p>}
    </>
  );
}
