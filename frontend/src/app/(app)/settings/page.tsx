"use client";
import * as React from "react";
import { ErrorNote, PageHeader } from "@/components/common";
import { useApp, useFetch } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, NativeSelect } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { fmtDate, label } from "@/lib/utils";

type Scoring = { weights: Record<string, number>; tiers: { min: number; label: string }[]; target_polymers: string[]; target_grade_categories: string[]; target_applications: string[]; decision_maker_titles: string[] };
type Schedule = Record<string, number>;

function ScoringCard({ admin }: { admin: boolean }) {
  const { data, reload } = useFetch<Scoring>("/settings/lead_scoring");
  const [edited, setW] = React.useState<Record<string, number> | null>(null);
  const [msg, setMsg] = React.useState<string | null>(null);
  if (!data) return null;
  const w = edited ?? data.weights;
  const total = Object.values(w).reduce((a, b) => a + Number(b || 0), 0);
  const save = async () => {
    try {
      await api("/settings/lead_scoring", { method: "PUT", body: JSON.stringify({ ...data, weights: w }) });
      const r = await api<{ rescored: number }>("/admin/rescore", { method: "POST" });
      setMsg(`Saved. ${r.rescored} companies rescored.`); reload();
    } catch (x) { setMsg((x as Error).message); }
  };
  return (
    <Card>
      <CardHeader><CardTitle>Lead scoring weights</CardTitle><CardDescription>Weights are normalised to 100. The score prioritises research effort; it is not a conversion probability.</CardDescription></CardHeader>
      <CardContent className="flex flex-col gap-2">
        {Object.entries(w).map(([k, v]) => (
          <div key={k} className="grid grid-cols-[1fr_90px] items-center gap-2"><Label>{label(k)}</Label>
            <Input type="number" min={0} disabled={!admin} value={v} onChange={(e) => setW({ ...w, [k]: Number(e.target.value) })} /></div>
        ))}
        <p className="text-xs text-muted-foreground">Total {total} → normalised to 100. Tiers: {data.tiers.map((t) => `${t.label} ≥ ${t.min}`).join(", ")}.</p>
        {admin && <Button className="self-start" onClick={save}>Save & rescore all</Button>}
        {msg && <p className="text-sm text-muted-foreground">{msg}</p>}
      </CardContent>
    </Card>
  );
}

function ScheduleCard({ admin }: { admin: boolean }) {
  const { data, reload } = useFetch<Schedule>("/settings/refresh_schedule");
  const [edited, setS] = React.useState<Schedule | null>(null);
  const s = edited ?? data;
  if (!s) return null;
  return (
    <Card>
      <CardHeader><CardTitle>Refresh schedule</CardTitle><CardDescription>Used by the scheduler worker (restart it after changes). Only enabled sources run.</CardDescription></CardHeader>
      <CardContent className="flex flex-col gap-2">
        {Object.entries(s).map(([k, v]) => (
          <div key={k} className="grid grid-cols-[1fr_90px] items-center gap-2"><Label>{label(k)}</Label>
            <Input type="number" min={1} disabled={!admin} value={v} onChange={(e) => setS({ ...s, [k]: Number(e.target.value) })} /></div>
        ))}
        {admin && <Button className="self-start" onClick={async () => { await api("/settings/refresh_schedule", { method: "PUT", body: JSON.stringify(s) }); reload(); }}>Save schedule</Button>}
      </CardContent>
    </Card>
  );
}

function CountriesCard({ admin }: { admin: boolean }) {
  const { meta, refreshMeta } = useApp();
  return (
    <Card>
      <CardHeader><CardTitle>Markets</CardTitle><CardDescription>Active markets drive automated discovery and official statistics. Add new countries in reference data.</CardDescription></CardHeader>
      <CardContent className="flex flex-wrap gap-1.5">
        {meta?.countries.map((c) => (
          <button key={c.code} disabled={!admin} onClick={async () => { await api(`/countries/${c.code}`, { method: "PATCH", body: JSON.stringify({ is_active: !c.is_active }) }); refreshMeta(); }}
            className={`rounded-md border px-2 py-1 text-xs ${c.is_active ? "border-primary bg-accent text-accent-foreground" : "text-muted-foreground"}`}>{c.name}</button>
        ))}
      </CardContent>
    </Card>
  );
}

function UsersCard() {
  const { data, reload, error } = useFetch<{ id: string; email: string; role: string; full_name: string | null; is_active: boolean; last_login_at: string | null }[]>("/auth/users");
  const [f, setF] = React.useState({ email: "", password: "", role: "analyst" });
  const [msg, setMsg] = React.useState<string | null>(null);
  return (
    <Card>
      <CardHeader><CardTitle>Users</CardTitle><CardDescription>Roles: admin (sources, settings), analyst (edit data, CRM), viewer (read-only).</CardDescription></CardHeader>
      <CardContent>
        <ErrorNote error={error} />
        <ul className="mb-3 flex flex-col divide-y text-sm">{data?.map((u) => <li key={u.id} className="flex justify-between py-1.5"><span>{u.email}</span><span className="text-xs text-muted-foreground">{u.role} · last login {fmtDate(u.last_login_at)}</span></li>)}</ul>
        <form className="grid gap-2 sm:grid-cols-4" onSubmit={async (e) => { e.preventDefault(); try { await api("/auth/users", { method: "POST", body: JSON.stringify(f) }); setMsg("User created"); setF({ email: "", password: "", role: "analyst" }); reload(); } catch (x) { setMsg((x as Error).message); } }}>
          <Input type="email" required placeholder="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
          <Input type="password" placeholder="password (10+ chars)" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
          <NativeSelect value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}><option value="analyst">Analyst</option><option value="viewer">Viewer</option><option value="admin">Admin</option></NativeSelect>
          <Button type="submit">Add user</Button>
        </form>
        {msg && <p className="mt-2 text-sm text-muted-foreground">{msg}</p>}
      </CardContent>
    </Card>
  );
}

function PrivacyCard() {
  const { data, reload } = useFetch<{ id: number; type: string; email: string; details: string | null; status: string; created_at: string }[]>("/privacy/requests");
  return (
    <Card>
      <CardHeader><CardTitle>Privacy requests</CardTitle><CardDescription>Public form at <a className="text-primary underline" href="/privacy" target="_blank">/privacy</a>. Opt-outs apply immediately; deletions remove the contact and add it to the suppression list.</CardDescription></CardHeader>
      <CardContent className="p-0"><Table>
        <THead><TR><TH>Received</TH><TH>Type</TH><TH>Email</TH><TH>Details</TH><TH>Status</TH><TH /></TR></THead>
        <TBody>
          {data?.map((p) => (
            <TR key={p.id}><TD className="text-xs">{fmtDate(p.created_at, true)}</TD><TD>{label(p.type)}</TD><TD className="text-xs">{p.email}</TD><TD className="max-w-48 text-xs">{p.details}</TD>
              <TD><Badge variant={p.status === "completed" ? "good" : "warn"}>{p.status}</Badge></TD>
              <TD className="whitespace-nowrap">{p.status !== "completed" && <Button size="sm" variant="outline" onClick={async () => {
                await api(`/privacy/requests/${p.id}/resolve`, { method: "POST", body: JSON.stringify({ status: "completed", apply_deletion: p.type === "deletion", notes: "Processed via settings" }) }); reload(); }}>
                {p.type === "deletion" ? "Delete & complete" : "Mark completed"}</Button>}</TD></TR>
          ))}
          {!data?.length && <TR><TD colSpan={6} className="py-6 text-center text-muted-foreground">No requests.</TD></TR>}
        </TBody>
      </Table></CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const { me } = useApp();
  const admin = me?.role === "admin";
  return (
    <>
      <PageHeader title="Settings" description={admin ? "Configuration for scoring, refresh workflows, markets, users and privacy." : "Read-only for your role."} />
      <div className="grid gap-4 lg:grid-cols-2">
        <ScoringCard admin={admin} />
        <ScheduleCard admin={admin} />
        <CountriesCard admin={admin} />
        {admin && <UsersCard />}
        {admin && <div className="lg:col-span-2"><PrivacyCard /></div>}
      </div>
    </>
  );
}
