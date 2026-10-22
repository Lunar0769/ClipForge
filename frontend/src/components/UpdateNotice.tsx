import { ArrowUpCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

/** Shows a small pill when a newer ClipForge version is tagged on GitHub. Silent when offline. */
export function UpdateNotice() {
  const [update, setUpdate] = useState<{ latest: string; url: string } | null>(null);

  useEffect(() => {
    let alive = true;
    api.updateStatus()
      .then((s) => alive && s.update_available && s.latest && setUpdate({ latest: s.latest, url: s.url }))
      .catch(() => undefined);
    return () => { alive = false; };
  }, []);

  if (!update) return null;
  return (
    <a
      href={update.url}
      target="_blank"
      rel="noreferrer"
      title="Update with: ./scripts/update.ps1"
      className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-3 py-1.5 text-xs font-medium text-emerald-400 transition hover:bg-emerald-500/25"
    >
      <ArrowUpCircle className="size-3.5" aria-hidden="true" />
      <span>v{update.latest} available</span>
    </a>
  );
}
