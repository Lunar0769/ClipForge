import clsx from "clsx";
import type { JobStatus } from "../lib/types";

const STYLES: Record<JobStatus, { label: string; className: string }> = {
  queued: { label: "Queued", className: "bg-surface-2 text-muted" },
  running: { label: "Processing", className: "bg-violet-brand/15 text-violet-400" },
  succeeded: { label: "Ready", className: "bg-emerald-500/15 text-emerald-400" },
  failed: { label: "Failed", className: "bg-red-500/15 text-red-400" },
  cancelled: { label: "Cancelled", className: "bg-surface-2 text-muted" },
};

export function StatusChip({ status }: { status: JobStatus }) {
  const style = STYLES[status];
  return (
    <span className={clsx("inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium", style.className)}>
      {status === "running" && <span className="size-1.5 animate-pulse rounded-full bg-current" />}
      {style.label}
    </span>
  );
}
