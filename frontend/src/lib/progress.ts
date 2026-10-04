import type { JobViewState, StageState } from "../features/processing/jobEvents";
import type { Job, StageInfo, StageStatus } from "./types";

export function stageFraction(stage?: StageState): number {
  if (!stage) return 0;
  if (stage.status === "done" || stage.status === "cached") return 1;
  if (stage.status === "pending") return 0;
  return stage.progress;
}

export function overallProgress(stages: StageInfo[], view: Pick<JobViewState, "jobStatus" | "stages">): number {
  if (view.jobStatus === "succeeded") return 1;
  const total = stages.reduce((sum, s) => sum + s.weight, 0);
  if (!total) return 0;
  return stages.reduce((sum, s) => sum + s.weight * stageFraction(view.stages[s.name]), 0) / total;
}

const CURRENT_STAGE_STATUS: Record<Job["status"], StageStatus> = {
  queued: "pending", running: "running", succeeded: "done", failed: "failed", cancelled: "cancelled",
};

/**
 * Stage states rebuilt from the REST job, for when there is no live event history
 * (e.g. the API restarted after the job finished): stages before `job.stage` are done,
 * `job.stage` reflects the job's status, later stages are waiting.
 */
export function stagesFromJob(stages: StageInfo[], job: Job): Record<string, StageState> {
  const total = stages.reduce((sum, s) => sum + s.weight, 0);
  const currentIndex = job.status === "succeeded" ? stages.length : stages.findIndex((s) => s.name === job.stage);
  const result: Record<string, StageState> = {};
  let before = 0;
  stages.forEach((stage, index) => {
    if (currentIndex < 0 || index > currentIndex) {
      result[stage.name] = { status: "pending", progress: 0, message: null };
    } else if (index < currentIndex) {
      result[stage.name] = { status: "done", progress: 1, message: null };
    } else {
      const own = stage.weight ? (job.progress * total - before) / stage.weight : 0;
      result[stage.name] = {
        status: CURRENT_STAGE_STATUS[job.status],
        progress: Math.min(1, Math.max(0, own)),
        message: null,
      };
    }
    before += stage.weight;
  });
  return result;
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
