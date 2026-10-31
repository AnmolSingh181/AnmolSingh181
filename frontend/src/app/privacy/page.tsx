"use client";
import * as React from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input, Label, NativeSelect, Textarea } from "@/components/ui/input";

export default function PrivacyPage() {
  const [type, setType] = React.useState("opt_out");
  const [email, setEmail] = React.useState("");
  const [details, setDetails] = React.useState("");
  const [msg, setMsg] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      const r = await api<{ message: string }>("/privacy/requests", { method: "POST", body: JSON.stringify({ request_type: type, email, details }) });
      setMsg(r.message);
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  return (
    <div className="mx-auto max-w-lg px-4 py-12">
      <h1 className="text-xl font-semibold">Personal data requests</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        We store business contact details collected from public company websites and authorised B2B sources. You can ask us to stop
        processing (opt-out), correct, or delete information about you. Opt-outs take effect immediately and the address is added to a
        suppression list so it is not collected again.
      </p>
      {msg ? <p className="mt-6 rounded-md border border-good/30 bg-good/10 p-3 text-sm text-good">{msg}</p> : (
        <form onSubmit={submit} className="mt-6 flex flex-col gap-3 rounded-lg border bg-card p-5">
          <div className="flex flex-col gap-1"><Label>Request</Label>
            <NativeSelect value={type} onChange={(e) => setType(e.target.value)}>
              <option value="opt_out">Opt out (stop using my details)</option>
              <option value="correction">Correct my details</option>
              <option value="deletion">Delete my details</option>
            </NativeSelect></div>
          <div className="flex flex-col gap-1"><Label>Your business email</Label><Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></div>
          <div className="flex flex-col gap-1"><Label>Details (optional)</Label><Textarea value={details} onChange={(e) => setDetails(e.target.value)} /></div>
          {err && <p className="text-sm text-bad">{err}</p>}
          <Button type="submit">Submit request</Button>
        </form>
      )}
    </div>
  );
}
