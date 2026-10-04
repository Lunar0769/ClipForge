import { describe, expect, it } from "vitest";
import { initialJobViewState } from "../features/processing/jobEvents";
import { makeJob } from "../test/fixtures";
import { estimateEtaFromBaseline, formatEta, overallProgress, stagesFromJob } from "./progress";

const stages = [
  { name: "ingest", label: "Importing video", weight: 1 },
  { name: "transcribe", label: "Transcribing speech", weight: 3 },
];

describe("progress", () => {
  it("weights stage progress", () => {
    const view = {
      ...initialJobViewState,
      stages: {
        ingest: { status: "cached" as const, progress: 1, message: null },
        transcribe: { status: "running" as const, progress: 0.5, message: null },
      },
    };
    expect(overallProgress(stages, view)).toBeCloseTo(0.625);
  });

  it("is complete when the job succeeded", () => {
    expect(overallProgress(stages, { ...initialJobViewState, jobStatus: "succeeded" })).toBe(1);
  });

  it("counts a succeeded job as complete even before any events arrive", () => {
    expect(overallProgress(stages, { jobStatus: "succeeded", stages: {} })).toBe(1);
  });

  it("estimates time left from observed progress only", () => {
    const base = { t: 0, progress: 0.5 };
    expect(estimateEtaFromBaseline(base, 10_000, 0.51)).toBeNull();
    expect(estimateEtaFromBaseline(base, 10_000, 0.75)).toBe(10);
    expect(estimateEtaFromBaseline(base, 10_000, 1)).toBeNull();
    expect(estimateEtaFromBaseline(null, 10_000, 0.75)).toBeNull();
    expect(estimateEtaFromBaseline(base, 0, 0.75)).toBeNull();
  });

  it("formats eta", () => {
    expect(formatEta(null)).toBe("Estimating time left…");
    expect(formatEta(42)).toBe("~42s left");
    expect(formatEta(200)).toBe("~4 min left");
  });
});

describe("stagesFromJob (no live events, e.g. after an API restart)", () => {
  it("marks every stage done for a succeeded job", () => {
    const derived = stagesFromJob(stages, makeJob({ status: "succeeded", stage: "transcribe", progress: 1 }));
    expect(derived.ingest.status).toBe("done");
    expect(derived.transcribe.status).toBe("done");
  });

  it("marks earlier stages done and the current one failed", () => {
    const derived = stagesFromJob(stages, makeJob({ status: "failed", stage: "transcribe", progress: 0.4 }));
    expect(derived.ingest).toEqual({ status: "done", progress: 1, message: null });
    expect(derived.transcribe.status).toBe("failed");
    expect(derived.transcribe.progress).toBeCloseTo(0.2);
  });

  it("marks the current stage cancelled and later ones pending", () => {
    const derived = stagesFromJob(stages, makeJob({ status: "cancelled", stage: "ingest", progress: 0.1 }));
    expect(derived.ingest.status).toBe("cancelled");
    expect(derived.transcribe.status).toBe("pending");
  });

  it("shows a running job's current stage as running, with overall progress preserved", () => {
    const job = makeJob({ status: "running", stage: "transcribe", progress: 0.625 });
    const derived = stagesFromJob(stages, job);
    expect(derived.ingest.status).toBe("done");
    expect(derived.transcribe).toEqual({ status: "running", progress: 0.5, message: null });
    expect(overallProgress(stages, { jobStatus: "running", stages: derived })).toBeCloseTo(0.625);
  });

  it("leaves everything pending for a queued job", () => {
    const derived = stagesFromJob(stages, makeJob({ status: "queued", stage: null }));
    expect(Object.values(derived).map((s) => s.status)).toEqual(["pending", "pending"]);
  });
});
