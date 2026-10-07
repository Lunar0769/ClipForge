export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export const TERMINAL: JobStatus[] = ["succeeded", "failed", "cancelled"];
export const isTerminal = (status?: JobStatus | null) => !!status && TERMINAL.includes(status);

export interface Job {
  id: string;
  project_id: string;
  status: JobStatus;
  stage: string | null;
  progress: number;
  error: string | null;
  error_hint: string | null;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  created_at: string;
  source_type: "url" | "upload";
  source_url: string | null;
  original_filename: string | null;
  title: string | null;
  video_id: string | null;
  duration_s: number | null;
  latest_job: Job | null;
}

export interface StageInfo {
  name: string;
  label: string;
  weight: number;
}

export type StageStatus = "pending" | "running" | "done" | "cached" | "failed" | "cancelled";

export interface JobEvent {
  job_id: string;
  type: "stage" | "progress" | "log" | "partial" | "job";
  stage: string | null;
  status: string | null;
  progress: number | null;
  message: string | null;
  data: Record<string, unknown> | null;
  ts: number;
}

export interface TranscriptLine {
  start: number;
  end: number;
  text: string;
}

export interface Transcript {
  language: string;
  duration_s: number;
  segments: (TranscriptLine & { id: number })[];
}

export interface SystemInfo {
  gpus: { name: string; memory_total_mb: number; driver: string }[];
  ffmpeg: boolean;
  nvenc: boolean;
}

export interface SeoPack {
  youtube_caption: string;
  tiktok_caption: string;
  reels_caption: string;
  hashtags: string[];
  cta: string;
}

export interface SubScores {
  hook: number;
  emotion: number;
  novelty: number;
  value: number;
  shareability: number;
  loop_potential: number;
}

export interface Clip {
  id: string;
  project_id: string;
  rank: number;
  start_s: number;
  end_s: number;
  title: string;
  hook_text: string;
  hook_type: string;
  why_viral: string;
  payoff_summary: string;
  score: number;
  sub_scores: SubScores;
  keywords: string[];
  emoji: string[];
  speakers: string[];
  video_file: string | null;
  thumbnail_file: string | null;
  seo: SeoPack | null;
  created_at: string;
  updated_at: string;
}
