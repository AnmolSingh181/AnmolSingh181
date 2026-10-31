"use client";
import * as React from "react";
import { Check, ChevronDown } from "lucide-react";
import { cn, label as fmt } from "@/lib/utils";

export type Option = { value: string; label?: string };

/** Compact checkbox dropdown used by every filter bar. */
export function MultiSelect({ placeholder, options, value, onChange, className }: {
  placeholder: string; options: Option[]; value: string[]; onChange: (v: string[]) => void; className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const toggle = (v: string) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  const text = value.length === 0 ? placeholder
    : value.length <= 2 ? value.map((v) => options.find((o) => o.value === v)?.label ?? fmt(v)).join(", ")
    : `${placeholder} (${value.length})`;
  return (
    <div ref={ref} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className={cn("flex h-9 w-full items-center justify-between gap-2 rounded-md border border-input bg-card px-2.5 text-left text-sm",
          value.length ? "text-foreground" : "text-muted-foreground")}
      >
        <span className="truncate">{text}</span>
        <ChevronDown className="size-4 shrink-0 opacity-60" />
      </button>
      {open && (
        <div className="absolute z-40 mt-1 max-h-72 w-full min-w-48 overflow-y-auto rounded-md border bg-card p-1 shadow-lg">
          {value.length > 0 && (
            <button type="button" className="w-full rounded px-2 py-1.5 text-left text-xs text-primary hover:bg-muted" onClick={() => onChange([])}>
              Clear selection
            </button>
          )}
          {options.map((o) => (
            <button type="button" key={o.value} onClick={() => toggle(o.value)}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-muted">
              <span className={cn("flex size-4 items-center justify-center rounded border", value.includes(o.value) && "border-primary bg-primary text-primary-foreground")}>
                {value.includes(o.value) && <Check className="size-3" />}
              </span>
              {o.label ?? fmt(o.value)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
