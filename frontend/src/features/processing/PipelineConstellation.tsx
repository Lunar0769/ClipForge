import clsx from "clsx";
import { AudioLines, Check, Download, Sparkles, X, type LucideIcon } from "lucide-react";
import { motion } from "motion/react";
import { stageFraction } from "../../lib/progress";
import type { StageInfo, StageStatus } from "../../lib/types";
import type { StageState } from "./jobEvents";

const ICONS: Record<string, LucideIcon> = { ingest: Download, transcribe: AudioLines };
const STATUS_TEXT: Record<StageStatus, string> = {
  pending: "Waiting", running: "In progress", done: "Done", cached: "Reused from cache",
  failed: "Failed", cancelled: "Cancelled",
};
const RADIUS = 24;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

function StageNode({ status, progress, Icon }: { status: StageStatus; progress: number; Icon: LucideIcon }) {
  const complete = status === "done" || status === "cached";
  return (
    <div className="relative grid size-14 shrink-0 place-items-center">
      {status === "running" && (
        <motion.span
          className="absolute inset-0 rounded-full bg-violet-brand/30"
          animate={{ scale: [1, 1.45], opacity: [0.6, 0] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: "easeOut" }}
        />
      )}
      <svg viewBox="0 0 56 56" className="absolute inset-0 -rotate-90" aria-hidden="true">
        <circle cx="28" cy="28" r={RADIUS} fill="none" stroke="var(--border)" strokeWidth="3" />
        <motion.circle
          cx="28" cy="28" r={RADIUS} fill="none" stroke="url(#stage-gradient)" strokeWidth="3" strokeLinecap="round"
          strokeDasharray={CIRCUMFERENCE}
          animate={{ strokeDashoffset: CIRCUMFERENCE * (1 - (complete ? 1 : status === "running" ? progress : 0)) }}
          transition={{ type: "spring", stiffness: 80, damping: 20 }}
        />
        <defs>
          <linearGradient id="stage-gradient" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#8b5cf6" />
            <stop offset="1" stopColor="#22d3ee" />
          </linearGradient>
        </defs>
      </svg>
      <span
        className={clsx(
          "relative grid size-10 place-items-center rounded-full transition-colors",
          complete && "bg-gradient-to-br from-violet-brand to-cyan-brand text-white",
          status === "failed" && "bg-red-500/20 text-red-400",
          !complete && status !== "failed" && "bg-surface-2",
        )}
      >
        {complete ? <Check className="size-5" /> : status === "failed" ? <X className="size-5" /> : <Icon className="size-5" />}
      </span>
    </div>
  );
}

export function PipelineConstellation({ stages, state }: { stages: StageInfo[]; state: Record<string, StageState> }) {
  return (
    <ol aria-label="Processing steps" className="mt-10 grid gap-4 sm:auto-cols-fr sm:grid-flow-col">
      {stages.map((stage, index) => {
        const current = state[stage.name];
        const status = current?.status ?? "pending";
        const previousDone = index > 0 && stageFraction(state[stages[index - 1].name]) === 1;
        return (
          <motion.li
            key={stage.name}
            data-status={status}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.08 }}
            className={clsx(
              "relative flex items-center gap-4 rounded-2xl border bg-surface p-4 sm:flex-col sm:items-start",
              status === "running" ? "border-violet-brand/50 shadow-[0_0_40px_-20px_var(--color-violet-brand)]" : "border-border",
            )}
          >
            {index > 0 && (
              <span aria-hidden="true" className="absolute -left-4 top-1/2 hidden h-0.5 w-4 bg-border sm:block">
                <motion.span
                  className="block h-full origin-left bg-gradient-to-r from-violet-brand to-cyan-brand"
                  animate={{ scaleX: previousDone ? 1 : 0 }}
                />
              </span>
            )}
            <StageNode status={status} progress={current?.progress ?? 0} Icon={ICONS[stage.name] ?? Sparkles} />
            <div className="min-w-0">
              <p className="font-medium">{stage.label}</p>
              <p className="truncate text-xs text-muted" aria-live="polite">{current?.message ?? STATUS_TEXT[status]}</p>
            </div>
          </motion.li>
        );
      })}
    </ol>
  );
}
