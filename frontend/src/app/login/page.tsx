"use client";
import * as React from "react";
import { api, setToken } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";

export default function LoginPage() {
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ access_token: string }>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
      setToken(r.access_token);
      window.location.href = "/";
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-lg border bg-card p-6 shadow-sm">
        <div className="mb-5 flex items-center gap-2">
          <span className="flex size-8 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground">PE</span>
          <div><h1 className="text-base font-semibold">Plastic Trading Intelligence</h1><p className="text-xs text-muted-foreground">Sign in to continue</p></div>
        </div>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1"><Label htmlFor="email">Email</Label>
            <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></div>
          <div className="flex flex-col gap-1"><Label htmlFor="pw">Password</Label>
            <Input id="pw" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></div>
          {error && <p className="text-sm text-bad">{error}</p>}
          <Button type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</Button>
        </div>
        <p className="mt-4 text-center text-xs text-muted-foreground"><a className="underline" href="/privacy">Data privacy requests</a></p>
      </form>
    </div>
  );
}
