import { describe, expect, it } from "vitest";
import { initialJobViewState } from "../features/processing/jobEvents";
import { estimateEta, formatEta, overallProgress } from "./progress";

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

  it("estimates time left", () => {
    expect(estimateEta(0, 10_000, 0.5)).toBe(10);
    expect(estimateEta(0, 10_000, 0.01)).toBeNull();
    expect(estimateEta(0, 10_000, 1)).toBeNull();
  });

  it("formats eta", () => {
    expect(formatEta(null)).toBe("Estimating time left…");
    expect(formatEta(42)).toBe("~42s left");
    expect(formatEta(200)).toBe("~4 min left");
  });
});
