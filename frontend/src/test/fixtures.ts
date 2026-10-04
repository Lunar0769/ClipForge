import type { Job, Project } from "../lib/types";

export function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "j1", project_id: "p1", status: "queued", stage: null, progress: 0,
    error: null, error_hint: null,
    created_at: "2026-10-03T10:00:00+00:00", updated_at: "2026-10-03T10:00:00+00:00",
    ...overrides,
  };
}

export function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: "p1", created_at: "2026-10-03T10:00:00+00:00", source_type: "url",
    source_url: "https://youtu.be/abc", original_filename: null, title: null,
    video_id: null, duration_s: null, latest_job: makeJob(),
    ...overrides,
  };
}
