export const UPLOAD_EXTENSIONS = [".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi"];

export function normalizeSourceUrl(input: string): string | null {
  let candidate = input.trim();
  if (!candidate) return null;
  if (!/^[a-z][a-z0-9+.-]*:/i.test(candidate)) candidate = `https://${candidate}`;
  try {
    const url = new URL(candidate);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (!url.hostname.includes(".")) return null;
    return url.toString();
  } catch {
    return null;
  }
}
