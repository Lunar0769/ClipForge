import type { Clip, Job, Project, StageInfo, SystemInfo, Transcript } from "./types";

const BASE = "/api";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

function detailMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length && typeof detail[0]?.msg === "string") return detail[0].msg;
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(BASE + path, { ...init, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, detailMessage(body, res.statusText || `Request failed (${res.status})`));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function upload(file: File, onProgress: (fraction: number) => void): Promise<Project> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/projects/upload`);
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as Project);
      else reject(new ApiError(xhr.status, detailMessage(xhr.response, "Upload failed")));
    };
    xhr.onerror = () => reject(new ApiError(0, "Upload failed — is the ClipForge API running?"));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export const api = {
  listProjects: () => request<Project[]>("/projects"),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  createFromUrl: (url: string) => request<Project>("/projects", { method: "POST", body: JSON.stringify({ url }) }),
  upload,
  retry: (projectId: string) => request<Project>(`/projects/${projectId}/retry`, { method: "POST" }),
  cancelJob: (jobId: string) => request<Job>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  deleteProject: (id: string) => request<void>(`/projects/${id}`, { method: "DELETE" }),
  stages: () => request<StageInfo[]>("/pipeline/stages"),
  transcript: (projectId: string) => request<Transcript>(`/projects/${projectId}/transcript`),
  system: () => request<SystemInfo>("/system"),
  listClips: (projectId: string) => request<Clip[]>(`/projects/${projectId}/clips`),
  getClip: (clipId: string) => request<Clip>(`/clips/${clipId}`),
  clipVideoUrl: (clipId: string) => `${BASE}/clips/${clipId}/video`,
  clipThumbnailUrl: (clipId: string) => `${BASE}/clips/${clipId}/thumbnail`,
  clipDownloadUrl: (clipId: string) => `${BASE}/clips/${clipId}/download`,
  exportProjectUrl: (projectId: string) => `${BASE}/projects/${projectId}/export`,
  rerenderClip: (clipId: string, subtitleStyle: string = "hormozi") =>
    request<Clip>(`/clips/${clipId}/render`, {
      method: "POST",
      body: JSON.stringify({ subtitle_style: subtitleStyle }),
    }),
};

export function jobEventsUrl(jobId: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}${BASE}/jobs/${jobId}/events`;
}
