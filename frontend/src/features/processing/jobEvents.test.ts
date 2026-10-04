import { describe, expect, it } from "vitest";
import type { JobEvent } from "../../lib/types";
import { initialJobViewState, jobEventsReducer, type JobAction } from "./jobEvents";

const ev = (e: Partial<JobEvent>): JobEvent => ({
  job_id: "j1", type: "log", stage: null, status: null, progress: null, message: null, data: null, ts: 0, ...e,
});

const reduce = (...actions: JobAction[]) => actions.reduce(jobEventsReducer, initialJobViewState);

describe("jobEventsReducer", () => {
  it("tracks stage lifecycle and progress", () => {
    const s = reduce(
      ev({ type: "stage", stage: "ingest", status: "running", progress: 0 }),
      ev({ type: "progress", stage: "ingest", progress: 0.4, message: "Downloading… 40%" }),
    );
    expect(s.stages.ingest).toEqual({ status: "running", progress: 0.4, message: "Downloading… 40%" });
    const done = jobEventsReducer(s, ev({ type: "stage", stage: "ingest", status: "done", progress: 1 }));
    expect(done.stages.ingest.status).toBe("done");
    expect(done.stages.ingest.progress).toBe(1);
  });

  it("appends transcript segments and language", () => {
    const s = reduce(
      ev({ type: "partial", stage: "transcribe", data: { kind: "segment", start: 0, end: 1, text: "Hello." } }),
      ev({ type: "partial", stage: "transcribe", data: { kind: "segment", start: 1, end: 2, text: "Bye." } }),
      ev({ type: "partial", stage: "transcribe", data: { kind: "language", language: "hi" } }),
    );
    expect(s.transcript.map((l) => l.text)).toEqual(["Hello.", "Bye."]);
    expect(s.language).toBe("hi");
  });

  it("records job outcome with hint", () => {
    const s = reduce(ev({ type: "job", status: "failed", message: "YouTube blocked the download.", data: { hint: "Update yt-dlp" } }));
    expect(s.jobStatus).toBe("failed");
    expect(s.error).toBe("YouTube blocked the download.");
    expect(s.hint).toBe("Update yt-dlp");
  });

  it("keeps unique log notices", () => {
    const s = reduce(ev({ type: "log", message: "No speech" }), ev({ type: "log", message: "No speech" }));
    expect(s.logs).toEqual(["No speech"]);
  });

  it("resets on reconnect so replayed history doesn't duplicate", () => {
    const s = reduce(
      ev({ type: "partial", data: { kind: "segment", start: 0, end: 1, text: "Hi." } }),
      { type: "reset" },
      ev({ type: "partial", data: { kind: "segment", start: 0, end: 1, text: "Hi." } }),
    );
    expect(s.transcript).toHaveLength(1);
  });
});
