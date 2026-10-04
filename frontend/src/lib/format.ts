import type { Project } from "./types";

const pad = (n: number) => String(n).padStart(2, "0");

export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

export function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  return `${Math.floor(total / 60)}:${pad(total % 60)}`;
}

export function formatRelative(iso: string, now: number = Date.now()): string {
  const diff = (now - Date.parse(iso)) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function projectTitle(project: Project): string {
  if (project.title) return project.title;
  if (project.original_filename) return project.original_filename;
  if (project.source_url) return project.source_url.replace(/^https?:\/\/(www\.)?/, "");
  return "Untitled project";
}

export function fileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot).toLowerCase() : "";
}
