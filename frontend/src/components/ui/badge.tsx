import * as React from "react";
import { cn } from "@/lib/utils";

const variants = {
  default: "bg-muted text-foreground border-border",
  primary: "bg-accent text-accent-foreground border-primary/20",
  good: "bg-good/12 text-good border-good/30",
  warn: "bg-warn/12 text-warn border-warn/30",
  bad: "bg-bad/12 text-bad border-bad/30",
  outline: "bg-transparent text-muted-foreground border-border",
};

export function Badge({ className, variant = "default", ...p }: React.HTMLAttributes<HTMLSpanElement> & { variant?: keyof typeof variants }) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-none whitespace-nowrap", variants[variant], className)}
      {...p}
    />
  );
}
