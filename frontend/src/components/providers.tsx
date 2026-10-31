"use client";
import * as React from "react";
import { api, getToken } from "@/lib/api";

export type Me = { id: string; email: string; role: string; full_name: string | null; demo_mode: boolean; auth_mode: string };
export type Meta = {
  countries: { code: string; name: string; is_active: boolean; region: string }[];
  materials: { code: string; name: string; is_target: boolean; hs_codes: string[]; notes: string | null }[];
  sources: { key: string; name: string }[];
  company_types: string[]; grade_categories: string[]; applications: string[]; relationships: string[];
  material_forms: string[]; verification_statuses: string[]; decision_roles: string[]; lead_stages: string[];
  lead_types: string[]; lead_priorities: string[]; tiers: string[]; departments: string[];
};

const Ctx = React.createContext<{ me: Me | null; meta: Meta | null; refreshMeta: () => void }>({ me: null, meta: null, refreshMeta: () => {} });

export function useApp() {
  return React.useContext(Ctx);
}

export function countryName(meta: Meta | null, code: string | null | undefined) {
  if (!code) return "—";
  return meta?.countries.find((c) => c.code === code)?.name ?? code;
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = React.useState<Me | null>(null);
  const [meta, setMeta] = React.useState<Meta | null>(null);
  const loadMeta = React.useCallback(() => { api<Meta>("/meta").then(setMeta).catch(() => {}); }, []);
  React.useEffect(() => {
    if (!getToken()) { window.location.replace("/login"); return; }
    api<Me>("/auth/me").then(setMe).catch(() => {});
    api<Meta>("/meta").then(setMeta).catch(() => {});
  }, []);
  if (!me) return <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">Loading…</div>;
  return <Ctx.Provider value={{ me, meta, refreshMeta: loadMeta }}>{children}</Ctx.Provider>;
}

/** Fetch helper with loading/error state; re-runs when `key` changes. */
export function useFetch<T>(path: string | null, params?: Record<string, unknown>, deps: unknown[] = []) {
  const [data, setData] = React.useState<T | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [doneKey, setDoneKey] = React.useState<string | null>(null);
  const [tick, setTick] = React.useState(0);
  const key = JSON.stringify(params ?? {});
  const reqKey = `${path}|${key}|${tick}|${JSON.stringify(deps)}`;
  React.useEffect(() => {
    if (!path) return;
    let alive = true;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    api<T>(path, { params: JSON.parse(key) as any })
      .then((d) => { if (alive) { setData(d); setError(null); } })
      .catch((e) => { if (alive) setError(e.message); })
      .finally(() => { if (alive) setDoneKey(reqKey); });
    return () => { alive = false; };
  }, [path, key, reqKey]);
  return { data, error, loading: !!path && doneKey !== reqKey, reload: () => setTick((t) => t + 1), setData };
}
