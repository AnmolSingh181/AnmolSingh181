"use client";
import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Check, ExternalLink, Plus, RefreshCw, ShieldCheck, Star, Trash2, X } from "lucide-react";
import { ErrorNote, ScoreBadge, Tags, VerificationBadge } from "@/components/common";
import { countryName, useApp, useFetch } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import type { CompanyDetail, CompanyMaterial } from "@/lib/types";
import { fmtDate, fmtNum, label } from "@/lib/utils";

const COMPONENT_LABEL: Record<string, string> = {
  material_relevance: "Material relevance", trading_activity: "Verified buying/selling activity",
  international_trade: "International trade activity", contact_completeness: "Contact completeness", data_recency: "Data recency",
};

function Evidence({ text, url }: { text: string | null; url: string | null }) {
  if (!text) return null;
  return (
    <blockquote className="mt-1 border-l-2 border-primary/40 pl-2 text-xs text-muted-foreground">
      “{text.length > 320 ? text.slice(0, 320) + "…" : text}”
      {url && <a href={url} target="_blank" rel="noreferrer" className="ml-1 inline-flex items-center text-primary hover:underline">source <ExternalLink className="ml-0.5 size-3" /></a>}
    </blockquote>
  );
}

function ReviewButtons({ m, onDone }: { m: CompanyMaterial; onDone: () => void }) {
  const review = async (status: string) => {
    await api(`/company-materials/${m.id}/review`, { method: "POST", body: JSON.stringify({ status }) });
    onDone();
  };
  if (m.review_status === "confirmed") return <Badge variant="good"><Check className="size-3" /> Confirmed</Badge>;
  if (m.review_status === "rejected") return <Badge variant="bad">Rejected</Badge>;
  return (
    <span className="flex gap-1">
      <Button size="sm" variant="outline" onClick={() => review("confirmed")} title="Evidence supports this classification"><Check /> Confirm</Button>
      <Button size="sm" variant="ghost" onClick={() => review("rejected")} title="Classification is wrong"><X /></Button>
    </span>
  );
}

function AddMaterial({ cid, onDone }: { cid: string; onDone: () => void }) {
  const { meta } = useApp();
  const [open, setOpen] = React.useState(false);
  const [f, setF] = React.useState<Record<string, string>>({ polymer: "LDPE", grade_category: "unknown", application: "unknown", relationship: "unknown", evidence: "" });
  const [err, setErr] = React.useState<string | null>(null);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    const body: Record<string, unknown> = { ...f };
    ["mfi", "density", "available_quantity", "required_quantity"].forEach((k) => { body[k] = f[k] ? Number(f[k]) : null; });
    try {
      await api(`/companies/${cid}/materials`, { method: "POST", body: JSON.stringify(body) });
      setOpen(false);
      onDone();
    } catch (x) { setErr((x as Error).message); }
  };
  const sel = (k: string, vals: string[]) => (
    <NativeSelect value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })}>{vals.map((v) => <option key={v} value={v}>{label(v)}</option>)}</NativeSelect>
  );
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}><Plus /> Add material</Button>
      <DialogContent title="Add material (manual, confirmed)" description="Record only what you have evidence for, e.g. an email, offer sheet or call note.">
        <form onSubmit={save} className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1"><Label>Polymer</Label>{sel("polymer", (meta?.materials ?? []).map((m) => m.code))}</div>
          <div className="flex flex-col gap-1"><Label>Grade</Label>{sel("grade_category", meta?.grade_categories ?? [])}</div>
          <div className="flex flex-col gap-1"><Label>Application</Label>{sel("application", meta?.applications ?? [])}</div>
          <div className="flex flex-col gap-1"><Label>Relationship</Label>{sel("relationship", meta?.relationships ?? [])}</div>
          {["mfi", "density", "grade_number", "brand", "colour", "available_quantity", "required_quantity"].map((k) => (
            <div key={k} className="flex flex-col gap-1"><Label>{label(k)}{k.includes("quantity") ? " (MT)" : ""}</Label>
              <Input value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></div>
          ))}
          <div className="flex flex-col gap-1 sm:col-span-2"><Label>Evidence *</Label>
            <Textarea required value={f.evidence} onChange={(e) => setF({ ...f, evidence: e.target.value })} placeholder="e.g. Offer email 12 Oct: 200 MT off-grade LDPE film, MFI 2" /></div>
          {err && <p className="text-sm text-bad sm:col-span-2">{err}</p>}
          <div className="sm:col-span-2"><Button type="submit">Save</Button></div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AddContact({ cid, onDone }: { cid: string; onDone: () => void }) {
  const [open, setOpen] = React.useState(false);
  const [f, setF] = React.useState<Record<string, string>>({});
  const [err, setErr] = React.useState<string | null>(null);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api(`/companies/${cid}/contacts`, { method: "POST", body: JSON.stringify({ contact_type: f.full_name ? "individual" : "general", ...f }) });
      setOpen(false);
      setF({});
      onDone();
    } catch (x) { setErr((x as Error).message); }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}><Plus /> Add contact</Button>
      <DialogContent title="Add contact" description="Leave name empty for a general company contact. Purchasing authority is never assumed: confirm it after speaking to the person.">
        <form onSubmit={save} className="grid gap-3 sm:grid-cols-2">
          {["full_name", "job_title", "email", "phone", "linkedin_url", "source_url"].map((k) => (
            <div key={k} className="flex flex-col gap-1"><Label>{label(k)}</Label><Input value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></div>
          ))}
          <div className="flex flex-col gap-1 sm:col-span-2"><Label>Where did this come from?</Label><Input value={f.evidence ?? ""} onChange={(e) => setF({ ...f, evidence: e.target.value })} placeholder="e.g. business card at Arabplast 2026" /></div>
          {err && <p className="text-sm text-bad sm:col-span-2">{err}</p>}
          <div className="sm:col-span-2"><Button type="submit">Save contact</Button></div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function LeadBox({ c, onDone }: { c: CompanyDetail; onDone: () => void }) {
  const save = async (lead_type: string) => {
    await api("/leads", { method: "POST", body: JSON.stringify({ company_id: c.id, lead_type, interested_materials: c.polymers }) });
    onDone();
  };
  if (c.lead) return (
    <Link href="/leads" className="flex items-center gap-2 rounded-md border bg-accent px-3 py-2 text-sm text-accent-foreground">
      <Star className="size-4" /> Saved lead · {label(c.lead.stage)} · {label(c.lead.priority)} priority
    </Link>
  );
  return (
    <div className="flex flex-wrap gap-2">
      <Button size="sm" onClick={() => save("potential_buyer")}><Star /> Save as potential buyer</Button>
      <Button size="sm" variant="outline" onClick={() => save("potential_supplier")}>Save as potential supplier</Button>
    </div>
  );
}

export default function CompanyPage() {
  const { id } = useParams<{ id: string }>();
  const { meta } = useApp();
  const router = useRouter();
  const { data: c, error, reload } = useFetch<CompanyDetail>(`/companies/${id}`);
  const [note, setNote] = React.useState("");
  const [msg, setMsg] = React.useState<string | null>(null);
  React.useEffect(() => { if (c?.redirect_to) router.replace(`/companies/${c.redirect_to}`); }, [c, router]);
  if (error) return <ErrorNote error={error} />;
  if (!c || c.redirect_to) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const current = c.materials.filter((m) => m.is_current);
  const history = c.materials.filter((m) => !m.is_current);
  const comps = c.lead_score_breakdown?.components ?? {};
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); setMsg(ok); reload(); } catch (x) { setMsg((x as Error).message); }
  };

  return (
    <>
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs text-muted-foreground"><Link href="/companies" className="hover:underline">Companies</Link> / {c.public_ref}</p>
          <h1 className="mt-1 flex flex-wrap items-center gap-2 text-xl font-semibold">{c.name} <ScoreBadge score={c.lead_score} tier={c.lead_tier} />
            {c.lead_tier && <span className="text-sm font-normal text-muted-foreground">{c.lead_tier}</span>}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {[c.city, c.state, countryName(meta, c.country_code)].filter((x) => x && x !== "—").join(", ")}
            {c.website && <> · <a className="text-primary hover:underline" href={c.website} target="_blank" rel="noreferrer">{c.domain ?? c.website}</a></>}
          </p>
          <div className="mt-2 flex flex-wrap gap-1"><Tags values={c.company_types} max={10} /> <Tags values={c.polymers} variant="primary" max={10} /></div>
        </div>
        <div className="flex flex-col gap-2 lg:items-end">
          <LeadBox c={c} onDone={reload} />
          <div className="flex gap-2">
            {c.website && <Button size="sm" variant="outline" onClick={() => act(() => api(`/companies/${c.id}/recrawl`, { method: "POST" }), "Website re-crawl queued")}><RefreshCw /> Re-crawl website</Button>}
            <Button size="sm" variant="outline" onClick={() => act(() => api(`/companies/${c.id}/rescore`, { method: "POST" }), "Score recalculated")}>Rescore</Button>
            <Button size="sm" variant="outline" onClick={() => act(() => api(`/companies/${c.id}`, { method: "PATCH", body: JSON.stringify({ mark_verified: true }) }), "Marked as verified today")}><ShieldCheck /> Mark verified</Button>
          </div>
          {msg && <p className="text-xs text-muted-foreground">{msg}</p>}
        </div>
      </div>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="materials">Materials ({current.length})</TabsTrigger>
          <TabsTrigger value="contacts">Contacts ({c.contacts.length})</TabsTrigger>
          <TabsTrigger value="shipments">Shipments ({c.shipments.length})</TabsTrigger>
          <TabsTrigger value="sources">Sources ({c.source_records.length})</TabsTrigger>
          <TabsTrigger value="verification">Verification</TabsTrigger>
          <TabsTrigger value="notes">Notes ({c.notes.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader><CardTitle>Company overview</CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-3 text-sm">
              {c.description ? <p>{c.description}</p> : <p className="text-muted-foreground">No description collected.</p>}
              <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
                {([["Email", c.email], ["Phone", c.phone], ["Address", c.address], ["LinkedIn", c.linkedin_url],
                  ["Registration", c.registration_number ? `${c.registration_number} ${c.registration_authority ?? ""}` : null],
                  ["First discovered", fmtDate(c.first_discovered_at)], ["Last seen", fmtDate(c.last_seen_at)],
                  ["Last verified", fmtDate(c.last_verified_at)], ["Website crawled", fmtDate(c.website_last_crawled_at)]] as [string, string | null][]).map(([k, v]) => (
                  <div key={k}><dt className="text-xs text-muted-foreground">{k}</dt><dd className="break-words">{v || "—"}</dd></div>
                ))}
              </dl>
              {c.aliases.length > 0 && <div><p className="text-xs text-muted-foreground">Also known as</p><p>{c.aliases.map((a) => a.alias).join(" · ")}</p></div>}
              <div><p className="text-xs text-muted-foreground">Countries of operation (from locations & shipments)</p>
                <p>{c.countries_of_operation.map((x) => countryName(meta, x)).join(", ") || "—"}</p></div>
              {c.locations.length > 0 && <div><p className="text-xs text-muted-foreground">Locations</p>
                <ul>{c.locations.map((l) => <li key={l.id}>{label(l.type)}: {[l.address, l.city, countryName(meta, l.country_code)].filter(Boolean).join(", ")}</li>)}</ul></div>}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Lead score {c.lead_score ?? "—"}/100</CardTitle>
              <CardDescription>{c.lead_score_breakdown?.note}</CardDescription></CardHeader>
            <CardContent className="flex flex-col gap-3">
              {Object.entries(comps).map(([k, v]) => (
                <div key={k}>
                  <div className="flex justify-between text-xs"><span className="font-medium">{COMPONENT_LABEL[k] ?? k}</span><span className="tabular-nums">{v.points} / {v.max}</span></div>
                  <div className="mt-1 h-1.5 rounded-full bg-muted"><div className="h-1.5 rounded-full bg-series-1" style={{ width: `${v.max ? (v.points / v.max) * 100 : 0}%` }} /></div>
                  <ul className="mt-1 text-xs text-muted-foreground">{v.reasons.map((r) => <li key={r}>• {r}</li>)}</ul>
                </div>
              ))}
            </CardContent>
          </Card>
          <Card className="lg:col-span-3">
            <CardHeader><CardTitle>Business classification</CardTitle><CardDescription>Each category keeps the sentence it was inferred from.</CardDescription></CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {!c.classifications.length && <p className="text-sm text-muted-foreground">Not classified yet.</p>}
              {c.classifications.map((x) => (
                <div key={x.id} className="rounded-md border p-2.5 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{label(x.category)}</span>
                    <span className="flex items-center gap-1">
                      <Badge variant="outline">{x.method}</Badge>
                      {x.review_status === "confirmed" ? <Badge variant="good">confirmed</Badge> : x.review_status === "rejected" ? <Badge variant="bad">rejected</Badge> : (
                        <>
                          <button className="rounded p-0.5 hover:bg-muted" title="Confirm" onClick={() => act(() => api(`/companies/${c.id}/classifications`, { method: "POST", body: JSON.stringify({ category: x.category, status: "confirmed" }) }), "Confirmed")}><Check className="size-3.5" /></button>
                          <button className="rounded p-0.5 hover:bg-muted" title="Reject" onClick={() => act(() => api(`/companies/${c.id}/classifications`, { method: "POST", body: JSON.stringify({ category: x.category, status: "rejected" }) }), "Rejected")}><X className="size-3.5" /></button>
                        </>
                      )}
                    </span>
                  </div>
                  <Evidence text={x.evidence_text} url={x.evidence_url} />
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="materials">
          <div className="mb-3 flex items-center justify-between"><p className="text-sm text-muted-foreground">Material portfolio and product specifications. Specs are shown only when stated verbatim in the source.</p><AddMaterial cid={c.id} onDone={reload} /></div>
          <div className="flex flex-col gap-3">
            {!current.length && <p className="text-sm text-muted-foreground">No materials identified.</p>}
            {current.map((m) => (
              <Card key={m.id}>
                <CardContent className="pt-4">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge variant="primary">{label(m.polymer)}</Badge><Badge>{label(m.grade_category)}</Badge><Badge>{label(m.application)}</Badge>
                      <Badge variant={m.relationship === "unknown" ? "warn" : "outline"}>{m.relationship === "unknown" ? "Buyer/seller unknown" : label(m.relationship)}</Badge>
                      {m.form && <Badge variant="outline">{label(m.form)}</Badge>}
                      <span className="text-xs text-muted-foreground">via {m.method} · confidence {Math.round(m.confidence * 100)}% · last seen {fmtDate(m.last_seen_at)}</span>
                      {m.review_status === "needs_review" && <Badge variant="warn">Needs review</Badge>}
                    </div>
                    <ReviewButtons m={m} onDone={reload} />
                  </div>
                  {(m.available_quantity || m.required_quantity) && <p className="mt-2 text-sm">
                    {m.available_quantity ? `Available: ${fmtNum(m.available_quantity)} ${m.quantity_unit ?? ""}${m.quantity_period ? " / " + m.quantity_period : ""}` : ""}
                    {m.required_quantity ? `Required: ${fmtNum(m.required_quantity)} ${m.quantity_unit ?? ""}${m.quantity_period ? " / " + m.quantity_period : ""}` : ""}</p>}
                  {m.specifications.some((s) => s.brand || s.grade_number || s.mfi != null || s.density != null || s.colour || s.origin_country || s.packaging) && (
                    <div className="mt-2 overflow-x-auto"><table className="text-xs"><thead><tr className="text-muted-foreground">{["Brand", "Grade no.", "MFI", "Density", "Colour", "Form", "Origin", "Packaging"].map((h) => <th key={h} className="pr-4 text-left font-medium">{h}</th>)}</tr></thead>
                      <tbody>{m.specifications.map((s) => <tr key={s.id}>{[s.brand, s.grade_number, s.mfi != null ? `${s.mfi}${s.mfi_conditions ? ` (${s.mfi_conditions})` : ""}` : null, s.density, s.colour, s.form, s.origin_country, s.packaging].map((v, i) => <td key={i} className="pr-4">{v ?? "—"}</td>)}</tr>)}</tbody></table></div>
                  )}
                  <Evidence text={m.evidence_text} url={m.evidence_url} />
                </CardContent>
              </Card>
            ))}
            {history.length > 0 && <details className="text-sm"><summary className="cursor-pointer text-muted-foreground">Historical material records ({history.length})</summary>
              <ul className="mt-2 flex flex-col gap-1">{history.map((m) => <li key={m.id}>{label(m.polymer)} · {label(m.grade_category)} · {label(m.relationship)} — last seen {fmtDate(m.last_seen_at)}</li>)}</ul></details>}
          </div>
        </TabsContent>

        <TabsContent value="contacts">
          <div className="mb-3 flex items-center justify-between"><p className="text-sm text-muted-foreground">General company contacts and named individuals. A title-based “likely decision-maker” is not a confirmed buyer.</p><AddContact cid={c.id} onDone={reload} /></div>
          <div className="rounded-lg border bg-card"><Table>
            <THead><TR><TH>Contact</TH><TH>Role</TH><TH>Email / phone</TH><TH>Status</TH><TH>Source</TH><TH /></TR></THead>
            <TBody>
              {c.contacts.map((p) => (
                <TR key={p.id}>
                  <TD>{p.full_name ?? <span className="text-muted-foreground">General contact</span>}<span className="block text-xs text-muted-foreground">{p.job_title ?? ""}</span></TD>
                  <TD><Badge variant={p.decision_role === "confirmed_decision_maker" ? "good" : p.decision_role === "likely_decision_maker" ? "primary" : "outline"}>{label(p.decision_role)}</Badge>{p.department && <span className="block text-xs text-muted-foreground">{p.department}</span>}</TD>
                  <TD className="text-xs">{p.email && <a className="block text-primary hover:underline" href={`mailto:${p.email}`}>{p.email}</a>}{p.phone && <span className="block">{p.phone}</span>}{p.linkedin_url && <a className="text-primary hover:underline" href={p.linkedin_url} target="_blank" rel="noreferrer">LinkedIn</a>}</TD>
                  <TD><VerificationBadge status={p.verification_status} /></TD>
                  <TD className="max-w-48 text-xs text-muted-foreground">{p.source_url ? <a className="break-all hover:underline" href={p.source_url} target="_blank" rel="noreferrer">{p.source_url.replace(/^https?:\/\//, "").slice(0, 40)}</a> : "manual"}</TD>
                  <TD className="whitespace-nowrap">
                    <Button size="sm" variant="ghost" title="Run syntax, MX and provider checks" onClick={() => act(() => api(`/contacts/${p.id}/verify`, { method: "POST" }), "Verification checks run")}>Verify</Button>
                    <Button size="sm" variant="ghost" title="I confirmed this contact personally" onClick={() => act(() => api(`/contacts/${p.id}/manual-verify`, { method: "POST", body: JSON.stringify({ result: "pass", confirm_decision_maker: p.contact_type === "individual" && confirm("Did this person confirm purchasing/sales authority?") }) }), "Manually verified")}><ShieldCheck /></Button>
                    <Button size="sm" variant="ghost" title="Delete and suppress" onClick={() => confirm("Delete this contact and suppress it from future collection?") && act(() => api(`/contacts/${p.id}`, { method: "DELETE" }), "Contact deleted")}><Trash2 /></Button>
                  </TD>
                </TR>
              ))}
              {!c.contacts.length && <TR><TD colSpan={6} className="py-6 text-center text-muted-foreground">No contacts collected.</TD></TR>}
            </TBody>
          </Table></div>
        </TabsContent>

        <TabsContent value="shipments">
          <div className="rounded-lg border bg-card"><Table>
            <THead><TR><TH>Date</TH><TH>Role</TH><TH>Counterparty</TH><TH>HS</TH><TH>Material</TH><TH>Description</TH><TH>Weight (kg)</TH><TH>Source</TH></TR></THead>
            <TBody>
              {c.shipments.map((s) => {
                const isImp = s.importer_company_id === c.id;
                const otherId = isImp ? s.exporter_company_id : s.importer_company_id;
                return (
                  <TR key={s.id}>
                    <TD className="whitespace-nowrap">{fmtDate(s.shipment_date)}</TD>
                    <TD><Badge variant="outline">{isImp ? "Importer" : "Exporter"}</Badge></TD>
                    <TD>{otherId ? <Link className="hover:text-primary" href={`/companies/${otherId}`}>{isImp ? s.exporter_name : s.importer_name}</Link> : (isImp ? s.exporter_name : s.importer_name) ?? "—"}
                      <span className="block text-xs text-muted-foreground">{isImp ? s.exporter_country : s.importer_country}</span></TD>
                    <TD>{s.hs_code ?? "—"}</TD>
                    <TD>{s.material ? <span title={s.material_inference ?? ""}>{label(s.material)}{s.material_inference === "ambiguous_hs" ? " *" : ""}</span> : "—"}</TD>
                    <TD className="max-w-64 truncate text-xs">{s.product_description}</TD>
                    <TD className="tabular-nums">{fmtNum(s.weight_kg)}</TD>
                    <TD className="text-xs text-muted-foreground">{s.source}</TD>
                  </TR>
                );
              })}
              {!c.shipments.length && <TR><TD colSpan={8} className="py-6 text-center text-muted-foreground">No shipment records linked to this company.</TD></TR>}
            </TBody>
          </Table></div>
          <p className="mt-2 text-xs text-muted-foreground">* HS 3901.10 covers both LDPE and some LLDPE; material inferred from the HS code only.</p>
        </TabsContent>

        <TabsContent value="sources">
          <div className="rounded-lg border bg-card"><Table>
            <THead><TR><TH>Source</TH><TH>Collected</TH><TH>Matched by</TH><TH>URL</TH></TR></THead>
            <TBody>{c.source_records.map((s) => (
              <TR key={s.id}><TD>{s.source}</TD><TD>{fmtDate(s.collected_at, true)}</TD>
                <TD><Badge variant="outline">{s.match_method}</Badge>{s.match_score ? <span className="ml-1 text-xs text-muted-foreground">{s.match_score}</span> : null}</TD>
                <TD className="max-w-80 break-all text-xs">{s.source_url ? <a className="text-primary hover:underline" href={s.source_url} target="_blank" rel="noreferrer">{s.source_url}</a> : "—"}</TD></TR>
            ))}</TBody>
          </Table></div>
        </TabsContent>

        <TabsContent value="verification">
          <div className="rounded-lg border bg-card"><Table>
            <THead><TR><TH>When</TH><TH>Contact</TH><TH>Check</TH><TH>Result</TH><TH>Status after</TH><TH>Provider</TH></TR></THead>
            <TBody>
              {c.verification_history.map((v, i) => (
                <TR key={i}><TD className="whitespace-nowrap text-xs">{fmtDate(v.checked_at, true)}</TD>
                  <TD className="text-xs">{c.contacts.find((x) => x.id === v.contact_id)?.email ?? c.contacts.find((x) => x.id === v.contact_id)?.full_name ?? v.contact_id.slice(0, 8)}</TD>
                  <TD>{label(v.check_type)}</TD><TD><Badge variant={v.result === "pass" ? "good" : v.result === "fail" ? "bad" : "outline"}>{v.result}</Badge></TD>
                  <TD><VerificationBadge status={v.status_after} /></TD><TD className="text-xs">{v.provider ?? "—"}</TD></TR>
              ))}
              {!c.verification_history.length && <TR><TD colSpan={6} className="py-6 text-center text-muted-foreground">No verification checks run yet.</TD></TR>}
            </TBody>
          </Table></div>
        </TabsContent>

        <TabsContent value="notes">
          <Card><CardContent className="pt-4">
            <form className="flex flex-col gap-2" onSubmit={async (e) => { e.preventDefault(); if (!note.trim()) return; await api(`/companies/${c.id}/notes`, { method: "POST", body: JSON.stringify({ body: note }) }); setNote(""); reload(); }}>
              <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Internal note (visible to your team only)" />
              <div><Button size="sm" type="submit">Add note</Button></div>
            </form>
            <ul className="mt-4 flex flex-col divide-y">{c.notes.map((n) => <li key={n.id} className="py-2 text-sm"><span className="text-xs text-muted-foreground">{fmtDate(n.created_at, true)}</span><p className="whitespace-pre-wrap">{n.body}</p></li>)}</ul>
          </CardContent></Card>
        </TabsContent>
      </Tabs>
    </>
  );
}
