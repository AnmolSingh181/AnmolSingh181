"use client";
import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bell, Building2, LineChart, Database, Gauge, LogOut, Menu, Moon, Search, Ship, Sparkles, Sun, Target, Users, X, ClipboardCheck, Settings } from "lucide-react";
import { setToken } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useApp, useFetch } from "./providers";

const NAV = [
  { href: "/", label: "Dashboard", icon: Gauge },
  { href: "/companies", label: "Company discovery", icon: Building2 },
  { href: "/search", label: "AI search", icon: Sparkles },
  { href: "/contacts", label: "Contacts", icon: Users },
  { href: "/prices", label: "Market prices", icon: LineChart },
  { href: "/trade", label: "Trade intelligence", icon: Ship },
  { href: "/leads", label: "Leads / CRM", icon: Target },
  { href: "/sources", label: "Data sources", icon: Database },
  { href: "/quality", label: "Data quality", icon: ClipboardCheck },
  { href: "/settings", label: "Settings", icon: Settings },
];

function readTheme(): boolean {
  const t = document.documentElement.dataset.theme;
  return t ? t === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
}
function subscribeTheme(cb: () => void) {
  window.addEventListener("pti-theme", cb);
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", cb);
  return () => { window.removeEventListener("pti-theme", cb); mq.removeEventListener("change", cb); };
}

function ThemeToggle() {
  const dark = React.useSyncExternalStore(subscribeTheme, readTheme, () => false);
  React.useEffect(() => {
    let t: string | null = null;
    try { t = localStorage.getItem("pti_theme"); } catch { /* ignore */ }
    if (t) { document.documentElement.dataset.theme = t; window.dispatchEvent(new Event("pti-theme")); }
  }, []);
  const flip = () => {
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("pti_theme", next); } catch { /* ignore */ }
    window.dispatchEvent(new Event("pti-theme"));
  };
  return (
    <button onClick={flip} className="rounded-md p-2 text-muted-foreground hover:bg-muted" aria-label="Toggle theme">
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}

type AlertList = { unread: number; items: { id: number; type: string; message: string; created_at: string; entity_type: string | null; entity_id: string | null }[] };

function Alerts() {
  const [open, setOpen] = React.useState(false);
  const { data, reload } = useFetch<AlertList>("/alerts", { limit: 15 });
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const markRead = async () => {
    const { api } = await import("@/lib/api");
    await api("/alerts/read-all", { method: "POST" });
    reload();
  };
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} className="relative rounded-md p-2 text-muted-foreground hover:bg-muted" aria-label="Alerts">
        <Bell className="size-4" />
        {!!data?.unread && <span className="absolute right-1 top-1 min-w-4 rounded-full bg-destructive px-1 text-[10px] font-semibold leading-4 text-white">{data.unread > 99 ? "99+" : data.unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-1 w-[min(92vw,380px)] rounded-lg border bg-card shadow-lg">
          <div className="flex items-center justify-between border-b px-3 py-2">
            <span className="text-sm font-medium">Alerts</span>
            <button className="text-xs text-primary" onClick={markRead}>Mark all read</button>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {!data?.items.length && <p className="p-4 text-sm text-muted-foreground">No alerts yet.</p>}
            {data?.items.map((a) => (
              <Link key={a.id} onClick={() => setOpen(false)} href={a.entity_type === "company" && a.entity_id ? `/companies/${a.entity_id}` : a.type === "new_shipment" ? "/trade" : "/sources"}
                className="block border-b px-3 py-2 text-sm last:border-0 hover:bg-muted">
                <span className="block text-[11px] uppercase tracking-wide text-muted-foreground">{a.type.replace(/_/g, " ")} · {new Date(a.created_at).toLocaleString()}</span>
                {a.message}
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { me } = useApp();
  const [mobile, setMobile] = React.useState(false);
  const nav = (
    <nav className="flex flex-col gap-0.5 p-2">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link key={href} href={href} onClick={() => setMobile(false)}
            className={cn("flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm", active ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
            <Icon className="size-4" /> {label}
          </Link>
        );
      })}
    </nav>
  );
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r bg-card lg:flex">
        <div className="flex h-14 items-center gap-2 border-b px-4">
          <span className="flex size-7 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground">PE</span>
          <div className="leading-tight"><p className="text-sm font-semibold">Plastic Intel</p><p className="text-[11px] text-muted-foreground">PE · PP · PVC · prices</p></div>
        </div>
        <div className="flex-1 overflow-y-auto">{nav}</div>
        <div className="border-t p-3 text-xs text-muted-foreground"><p className="truncate">{me?.email}</p><p className="capitalize">{me?.role}</p></div>
      </aside>
      {mobile && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobile(false)} />
          <div className="absolute inset-y-0 left-0 w-64 border-r bg-card">
            <div className="flex h-14 items-center justify-between border-b px-4"><span className="text-sm font-semibold">Plastic Intel</span>
              <button onClick={() => setMobile(false)} aria-label="Close menu"><X className="size-4" /></button></div>
            {nav}
          </div>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-card/95 px-4 backdrop-blur">
          <button className="rounded-md p-2 hover:bg-muted lg:hidden" onClick={() => setMobile(true)} aria-label="Open menu"><Menu className="size-4" /></button>
          <Link href="/search" className="flex h-9 min-w-0 max-w-md flex-1 items-center gap-2 rounded-md border border-input bg-background px-3 text-sm text-muted-foreground hover:border-primary/40">
            <Search className="size-4" /><span className="truncate">Ask: “recycled HDPE buyers in Vietnam”</span>
          </Link>
          <div className="ml-auto flex shrink-0 items-center">
            <ThemeToggle />
            <Alerts />
            <button className="rounded-md p-2 text-muted-foreground hover:bg-muted" aria-label="Sign out"
              onClick={() => { setToken(null); window.location.href = "/login"; }}><LogOut className="size-4" /></button>
          </div>
        </header>
        {me?.demo_mode && (
          <div className="border-b border-warn/30 bg-warn/10 px-4 py-1.5 text-xs text-warn">
            DEMO ENVIRONMENT — records marked [DEMO] are synthetic and must not be used as business intelligence.
          </div>
        )}
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-5 sm:px-6">{children}</main>
      </div>
    </div>
  );
}
