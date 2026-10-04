import type { JobEvent, JobStatus, StageStatus, TranscriptLine } from "../../lib/types";

export interface StageState {
  status: StageStatus;
  progress: number;
  message: string | null;
}

export interface JobViewState {
  jobStatus: JobStatus | null;
  stages: Record<string, StageState>;
  transcript: TranscriptLine[];
  logs: string[];
  error: string | null;
  hint: string | null;
  language: string | null;
}

export const initialJobViewState: JobViewState = {
  jobStatus: null, stages: {}, transcript: [], logs: [], error: null, hint: null, language: null,
};

export type JobAction = JobEvent | { type: "reset" };

export function jobEventsReducer(state: JobViewState, action: JobAction): JobViewState {
  if (action.type === "reset") return initialJobViewState;
  const event = action;
  switch (event.type) {
    case "stage": {
      if (!event.stage) return state;
      const prev = state.stages[event.stage];
      return {
        ...state,
        stages: {
          ...state.stages,
          [event.stage]: {
            status: (event.status as StageStatus) ?? prev?.status ?? "running",
            progress: event.progress ?? prev?.progress ?? 0,
            message: event.message ?? (event.status === "running" ? null : prev?.message ?? null),
          },
        },
      };
    }
    case "progress": {
      if (!event.stage) return state;
      const prev = state.stages[event.stage];
      return {
        ...state,
        stages: {
          ...state.stages,
          [event.stage]: { status: "running", progress: event.progress ?? prev?.progress ?? 0, message: event.message ?? prev?.message ?? null },
        },
      };
    }
    case "partial": {
      const data = event.data ?? {};
      if (data.kind === "segment") {
        const line: TranscriptLine = { start: Number(data.start), end: Number(data.end), text: String(data.text) };
        return { ...state, transcript: [...state.transcript, line] };
      }
      if (data.kind === "language") return { ...state, language: String(data.language) };
      return state;
    }
    case "log":
      return event.message && !state.logs.includes(event.message)
        ? { ...state, logs: [...state.logs, event.message].slice(-20) }
        : state;
    case "job":
      return {
        ...state,
        jobStatus: event.status as JobStatus,
        error: event.status === "failed" ? event.message : null,
        hint: event.status === "failed" ? ((event.data?.hint as string | undefined) ?? null) : null,
      };
    default:
      return state;
  }
}
