import type { JobViewState, StageState } from "../features/processing/jobEvents";
import type { StageInfo } from "./types";

export function stageFraction(stage?: StageState): number {
  if (!stage) return 0;
  if (stage.status === "done" || stage.status === "cached") return 1;
  if (stage.status === "pending") return 0;
  return stage.progress;
}

export function overallProgress(stages: StageInfo[], view: JobViewState): number {
  if (view.jobStatus === "succeeded") return 1;
  const total = stages.reduce((sum, s) => sum + s.weight, 0);
  if (!total) return 0;
  return stages.reduce((sum, s) => sum + s.weight * stageFraction(view.stages[s.name]), 0) / total;
}

export interface EtaBaseline {
  t: number;
  progress: number;
}

/** ETA from progress this client actually watched: needs at least 2% of observed movement. */
export function estimateEtaFromBaseline(baseline: EtaBaseline | null, nowMs: number, progress: number): number | null {
  if (!baseline || progress >= 1) return null;
  const gained = progress - baseline.progress;
  const elapsed = (nowMs - baseline.t) / 1000;
  if (gained < 0.02 || elapsed <= 0) return null;
  return Math.round((elapsed * (1 - progress)) / gained);
}

export function formatEta(seconds: number | null): string {
  if (seconds == null) return "Estimating time left…";
  if (seconds < 60) return `~${seconds}s left`;
  return `~${Math.ceil(seconds / 60)} min left`;
}
