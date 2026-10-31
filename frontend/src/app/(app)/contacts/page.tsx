"use client";
import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Empty, ErrorNote, PageHeader, Pager, VerificationBadge } from "@/components/common";
import { countryName, useApp, useFetch } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Input, NativeSelect } from "@/components/ui/input";
import { MultiSelect } from "@/components/ui/multi-select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import type { Contact } from "@/lib/types";
import { label } from "@/lib/utils";

function ContactsInner() {
  const { meta } = useApp();
  const sp = useSearchParams();
  const [q, setQ] = React.useState("");
  const [title, setTitle] = React.useState("");
  const [country, setCountry] = React.useState<string[]>(sp.getAll("country"));
  const [department, setDepartment] = React.useState<string[]>([]);
  const [material, setMaterial] = React.useState<string[]>([]);
  const [verification, setVerification] = React.useState<string[]>(sp.getAll("verification"));
  const [role, setRole] = React.useState<string[]>([]);
  const [type, setType] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [dq, setDq] = React.useState({ q: "", title: "" });
  React.useEffect(() => { const t = setTimeout(() => { setDq({ q, title }); setPage(1); }, 350); return () => clearTimeout(t); }, [q, title]);
  const { data, error } = useFetch<{ total: number; items: Contact[] }>("/contacts", {
    q: dq.q, title: dq.title, country, department, material, verification, decision_role: role, contact_type: type, page, page_size: 50,
  });
  return (
    <>
      <PageHeader title="Contact intelligence" description="Company contacts and named people from public business pages and authorised providers. Opted-out contacts are never shown." />
      <div className="mb-4 grid grid-cols-1 gap-2 rounded-lg border bg-card p-3 sm:grid-cols-2 lg:grid-cols-4">
        <Input placeholder="Name, email or company…" value={q} onChange={(e) => setQ(e.target.value)} />
        <Input placeholder="Job title contains… (e.g. purchas)" value={title} onChange={(e) => setTitle(e.target.value)} />
        <MultiSelect placeholder="Country" value={country} onChange={(v) => { setCountry(v); setPage(1); }} options={(meta?.countries ?? []).map((c) => ({ value: c.code, label: c.name }))} />
        <MultiSelect placeholder="Department" value={department} onChange={(v) => { setDepartment(v); setPage(1); }} options={(meta?.departments ?? []).map((d) => ({ value: d, label: d }))} />
        <MultiSelect placeholder="Company material" value={material} onChange={(v) => { setMaterial(v); setPage(1); }} options={(meta?.materials ?? []).map((m) => ({ value: m.code }))} />
        <MultiSelect placeholder="Verification status" value={verification} onChange={(v) => { setVerification(v); setPage(1); }} options={(meta?.verification_statuses ?? []).map((v) => ({ value: v }))} />
        <MultiSelect placeholder="Decision role" value={role} onChange={(v) => { setRole(v); setPage(1); }} options={(meta?.decision_roles ?? []).map((v) => ({ value: v }))} />
        <NativeSelect value={type} onChange={(e) => { setType(e.target.value); setPage(1); }}><option value="">All contact types</option><option value="individual">Individuals</option><option value="general">General company contacts</option></NativeSelect>
      </div>
      <ErrorNote error={error} />
      {data && data.total === 0 ? <Empty title="No contacts match">Contacts are collected from official company websites, imports and authorised enrichment providers.</Empty> : (
        <div className="rounded-lg border bg-card">
          <Table>
            <THead><TR><TH>Contact</TH><TH>Company</TH><TH>Role</TH><TH>Email / phone</TH><TH>Verification</TH><TH>Source</TH></TR></THead>
            <TBody>
              {data?.items.map((c) => (
                <TR key={c.id}>
                  <TD className="min-w-40">{c.full_name ?? <span className="text-muted-foreground">General contact</span>}<span className="block text-xs text-muted-foreground">{c.job_title ?? ""}</span></TD>
                  <TD className="min-w-40"><Link href={`/companies/${c.company_id}`} className="hover:text-primary">{c.company_name}</Link><span className="block text-xs text-muted-foreground">{countryName(meta, c.company_country)}</span></TD>
                  <TD><Badge variant={c.decision_role === "confirmed_decision_maker" ? "good" : c.decision_role === "likely_decision_maker" ? "primary" : "outline"}>{label(c.decision_role)}</Badge>{c.department && <span className="block text-xs text-muted-foreground">{c.department}</span>}</TD>
                  <TD className="text-xs">{c.email && <a className="block text-primary hover:underline" href={`mailto:${c.email}`}>{c.email}</a>}{c.phone && <span className="block">{c.phone}</span>}{c.linkedin_url && <a className="text-primary hover:underline" href={c.linkedin_url} target="_blank" rel="noreferrer">LinkedIn</a>}</TD>
                  <TD><VerificationBadge status={c.verification_status} /></TD>
                  <TD className="max-w-48 break-all text-xs text-muted-foreground">{c.source_url ? <a className="hover:underline" href={c.source_url} target="_blank" rel="noreferrer">{c.source_url.replace(/^https?:\/\//, "").slice(0, 40)}</a> : "manual / import"}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
          {data && <Pager page={page} pageSize={50} total={data.total} onPage={setPage} />}
        </div>
      )}
    </>
  );
}

export default function ContactsPage() {
  return <React.Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}><ContactsInner /></React.Suspense>;
}
