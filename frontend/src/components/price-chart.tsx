"use client";
import * as React from "react";
import { cn, fmtDate } from "@/lib/utils";

/**
 * Time-series line chart (inline SVG, no dependency).
 * Dataviz spec: one y-axis, 2px lines, recessive grid, categorical colours in fixed slot order assigned by the caller
 * per entity (never by rank), legend whenever >= 2 series plus direct end labels for <= 4, crosshair + tooltip on hover.
 */
export type ChartLine = { id: string | number; label: string; color: string; data: { t: string; v: number }[] };

export const SERIES_COLORS = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`);

function niceTicks(min: number, max: number, count = 5): number[] {
  if (!isFinite(min) || !isFinite(max)) return [];
  if (min === max) { const pad = Math.abs(min) * 0.05 || 1; min -= pad; max += pad; }
  const raw = (max - min) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.floor(min / step) * step; v <= max + step * 0.001; v += step) out.push(+v.toFixed(10));
  if (out[out.length - 1] < max) out.push(out[out.length - 1] + step);
  return out;
}

function fmtVal(v: number): string {
  const a = Math.abs(v);
  return v.toLocaleString(undefined, { maximumFractionDigits: a >= 1000 ? 0 : a >= 10 ? 1 : 3 });
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = React.useRef<T>(null);
  const [w, setW] = React.useState(640);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(260, Math.floor(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

export function LineChart({ lines, unit, height = 280, className }: { lines: ChartLine[]; unit: string; height?: number; className?: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = React.useState<number | null>(null);
  const parsed = React.useMemo(() => lines.filter((l) => l.data.length).map((l) => ({ ...l, pts: l.data.map((d) => ({ t: new Date(d.t).getTime(), v: d.v })) })), [lines]);
  const direct = parsed.length <= 4;
  const single = parsed.length === 1;
  const m = { top: 12, right: single ? 56 : direct ? Math.min(120, width * 0.28) : 16, bottom: 26, left: 52 };
  const iw = Math.max(10, width - m.left - m.right), ih = height - m.top - m.bottom;
  const all = parsed.flatMap((l) => l.pts);
  if (!all.length) return <div ref={ref} className={cn("flex items-center justify-center text-sm text-muted-foreground", className)} style={{ height }}>No data in this range.</div>;
  const t0 = Math.min(...all.map((p) => p.t)), t1 = Math.max(...all.map((p) => p.t));
  const yt = niceTicks(Math.min(...all.map((p) => p.v)), Math.max(...all.map((p) => p.v)));
  const y0 = yt[0], y1 = yt[yt.length - 1];
  const x = (t: number) => m.left + (t1 === t0 ? iw / 2 : ((t - t0) / (t1 - t0)) * iw);
  const y = (v: number) => m.top + ih - ((v - y0) / (y1 - y0 || 1)) * ih;
  const nx = t1 === t0 ? 1 : Math.max(2, Math.min(6, Math.floor(iw / 110)));
  const xTicks: number[] = Array.from({ length: nx }, (_, i) => (nx === 1 ? t0 : t0 + ((t1 - t0) * i) / (nx - 1)));
  const span = t1 - t0;
  const fmtX = (t: number) => new Date(t).toLocaleDateString(undefined, span > 400 * 864e5 ? { month: "short", year: "2-digit" } : { month: "short", day: "numeric" });

  // hover: snap to the nearest observed timestamp across all series
  const times = Array.from(new Set(all.map((p) => p.t))).sort((a, b) => a - b);
  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const r = (e.currentTarget as SVGRectElement).getBoundingClientRect();
    const tx = t0 + ((e.clientX - r.left) / r.width) * (t1 - t0);
    let best = times[0];
    for (const t of times) if (Math.abs(t - tx) < Math.abs(best - tx)) best = t;
    setHover(best);
  };
  const atHover = hover == null ? [] : parsed.map((l) => {
    let best: { t: number; v: number } | null = null;
    for (const p of l.pts) if (p.t <= hover && (!best || p.t > best.t)) best = p;
    return { l, p: best };
  }).filter((r) => r.p) as { l: (typeof parsed)[number]; p: { t: number; v: number } }[];

  // direct labels: stagger to avoid collisions
  const ends = parsed.map((l) => ({ l, yy: y(l.pts[l.pts.length - 1].v) })).sort((a, b) => a.yy - b.yy);
  for (let i = 1; i < ends.length; i++) if (ends[i].yy - ends[i - 1].yy < 14) ends[i].yy = ends[i - 1].yy + 14;

  return (
    <div className={cn("w-full", className)}>
      {parsed.length >= 2 && (
        <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Legend">
          {parsed.map((l) => <span key={l.id} className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4 rounded-full" style={{ background: l.color }} />{l.label}</span>)}
        </div>
      )}
      <div ref={ref} className="relative w-full">
        <svg width={width} height={height} role="img" aria-label={`Price chart in ${unit}`} className="block select-none">
          {yt.map((v) => (
            <g key={v}>
              <line x1={m.left} x2={m.left + iw} y1={y(v)} y2={y(v)} stroke="var(--grid)" strokeWidth={1} />
              <text x={m.left - 6} y={y(v)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[10px] tabular-nums">{fmtVal(v)}</text>
            </g>
          ))}
          {xTicks.map((t, i) => <text key={i} x={x(t)} y={height - 8} textAnchor={i === 0 ? "start" : i === xTicks.length - 1 ? "end" : "middle"} className="fill-muted-foreground text-[10px]">{fmtX(t)}</text>)}
          {parsed.map((l) => (
            <g key={l.id}>
              <path d={l.pts.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join("")} fill="none" stroke={l.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
              {l.pts.length === 1 && <circle cx={x(l.pts[0].t)} cy={y(l.pts[0].v)} r={4} fill={l.color} stroke="var(--card)" strokeWidth={2} />}
            </g>
          ))}
          {direct && ends.map(({ l, yy }) => (
            <g key={l.id}>
              <circle cx={x(l.pts[l.pts.length - 1].t)} cy={y(l.pts[l.pts.length - 1].v)} r={3} fill={l.color} stroke="var(--card)" strokeWidth={2} />
              <text x={m.left + iw + 8} y={yy} dy="0.32em" className="fill-foreground text-[10px] font-medium">
                {fmtVal(l.pts[l.pts.length - 1].v)}{!single && <tspan className="fill-muted-foreground font-normal"> {l.label.length > 14 ? l.label.slice(0, 13) + "…" : l.label}</tspan>}
              </text>
            </g>
          ))}
          {hover != null && (
            <g pointerEvents="none">
              <line x1={x(hover)} x2={x(hover)} y1={m.top} y2={m.top + ih} stroke="var(--muted-foreground)" strokeWidth={1} strokeDasharray="3 3" />
              {atHover.map(({ l, p }) => <circle key={l.id} cx={x(p.t)} cy={y(p.v)} r={4} fill={l.color} stroke="var(--card)" strokeWidth={2} />)}
            </g>
          )}
          <rect x={m.left} y={m.top} width={iw} height={ih} fill="transparent" onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
        </svg>
        {hover != null && atHover.length > 0 && (
          <div className="pointer-events-none absolute top-1 z-10 min-w-40 rounded-md border bg-card px-2.5 py-2 text-xs shadow-md"
            style={x(hover) > width / 2 ? { right: width - x(hover) + 10 } : { left: x(hover) + 10 }}>
            <p className="mb-1 font-medium">{fmtDate(new Date(hover).toISOString())}</p>
            {atHover.sort((a, b) => b.p.v - a.p.v).map(({ l, p }) => (
              <p key={l.id} className="flex items-center justify-between gap-3">
                <span className="inline-flex items-center gap-1.5 text-muted-foreground"><span className="size-2 rounded-full" style={{ background: l.color }} />{l.label}</span>
                <span className="font-medium tabular-nums">{fmtVal(p.v)}</span>
              </p>
            ))}
            <p className="mt-1 text-[10px] text-muted-foreground">{unit}</p>
          </div>
        )}
      </div>
    </div>
  );
}

/** Tiny trend line for table rows (single series, no axes; the row shows the numbers). */
export function Sparkline({ data, width = 96, height = 26 }: { data: { v: number }[]; width?: number; height?: number }) {
  if (data.length < 2) return <span className="text-xs text-muted-foreground">—</span>;
  const vs = data.map((d) => d.v), lo = Math.min(...vs), hi = Math.max(...vs);
  const pts = vs.map((v, i) => `${((i / (vs.length - 1)) * (width - 4) + 2).toFixed(1)},${(height - 3 - ((v - lo) / (hi - lo || 1)) * (height - 6)).toFixed(1)}`);
  const last = pts[pts.length - 1].split(",");
  return (
    <svg width={width} height={height} aria-hidden className="block">
      <polyline points={pts.join(" ")} fill="none" stroke="var(--series-1)" strokeWidth={1.5} strokeLinejoin="round" />
      <circle cx={last[0]} cy={last[1]} r={2.5} fill="var(--series-1)" />
    </svg>
  );
}
