import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { HardDrive, Trash2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Link } from "react-router";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Skeleton } from "../../components/Skeleton";
import { StatusChip } from "../../components/StatusChip";
import { api } from "../../lib/api";
import { formatBytes, formatDuration, formatRelative, projectTitle } from "../../lib/format";
import type { Project } from "../../lib/types";

const PAGE = 9;

export function RecentProjects() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["projects"], queryFn: api.listProjects });
  const [showAll, setShowAll] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Project | null>(null);
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteProject(id),
    onSuccess: () => {
      setPendingDelete(null);
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  if (isLoading) {
    return (
      <section className="mx-auto grid max-w-6xl gap-4 px-4 pb-24 sm:grid-cols-2 sm:px-6 lg:grid-cols-3">
        {[0, 1, 2].map((i) => <Skeleton key={i} className="h-28 rounded-2xl" />)}
      </section>
    );
  }
  if (!data?.length) return null;

  const visible = showAll ? data : data.slice(0, PAGE);
  // Projects made from the same video share one cached download: count each cache once.
  const caches = new Map(data.filter((p) => p.video_id).map((p) => [p.video_id, p.cache_bytes ?? 0]));
  const totalBytes = data.reduce((sum, p) => sum + (p.project_bytes ?? 0), 0)
    + [...caches.values()].reduce((a, b) => a + b, 0);

  return (
    <section className="mx-auto max-w-6xl px-4 pb-24 sm:px-6">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <h2 className="font-display text-2xl font-semibold tracking-tight">Recent projects</h2>
        {totalBytes > 0 && (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted">
            <HardDrive className="size-3.5" aria-hidden="true" />
            {data.length} projects · {formatBytes(totalBytes)} on disk
          </span>
        )}
      </div>
      <motion.ul
        initial="hidden"
        animate="show"
        variants={{ show: { transition: { staggerChildren: 0.06 } } }}
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      >
        <AnimatePresence initial={false}>
          {visible.map((project) => (
            <motion.li
              key={project.id}
              layout
              exit={{ opacity: 0, scale: 0.96 }}
              className="group relative min-w-0"
              variants={{ hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0 } }}
            >
              <Link
                to={`/projects/${project.id}`}
                className="block h-full rounded-2xl border border-border bg-surface p-5 pr-12 transition hover:-translate-y-0.5 hover:border-violet-brand/50 hover:bg-surface-2"
              >
                <div className="flex items-start justify-between gap-3">
                  <span className="line-clamp-2 min-w-0 font-medium [overflow-wrap:anywhere]">{projectTitle(project)}</span>
                  {project.latest_job && <StatusChip status={project.latest_job.status} />}
                </div>
                <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                  <span>{project.source_type === "url" ? "Link" : "Upload"}</span>
                  {project.duration_s != null && <span>{formatDuration(project.duration_s)}</span>}
                  <span>{formatRelative(project.created_at)}</span>
                  {!!project.storage_bytes && <span>{formatBytes(project.storage_bytes)}</span>}
                </div>
              </Link>
              {/* Sibling of the link (not inside it) so the button stays its own focus/click target */}
              <button
                type="button"
                onClick={() => setPendingDelete(project)}
                aria-label={`Delete project ${projectTitle(project)}`}
                title="Delete project"
                className="absolute bottom-4 right-4 grid size-8 place-items-center rounded-full text-muted opacity-70 transition hover:bg-red-500/15 hover:text-red-400 hover:opacity-100 focus-visible:opacity-100 sm:opacity-0 sm:group-hover:opacity-100"
              >
                <Trash2 className="size-4" />
              </button>
            </motion.li>
          ))}
        </AnimatePresence>
      </motion.ul>
      {data.length > PAGE && (
        <div className="mt-6 text-center">
          <button type="button" onClick={() => setShowAll((v) => !v)}
            className="rounded-full border border-border px-4 py-2 text-sm text-muted transition hover:bg-surface-2 hover:text-fg">
            {showAll ? "Show fewer" : `Show all ${data.length} projects`}
          </button>
        </div>
      )}
      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete this project?"
        message={pendingDelete ? `All clips, renders and exports for “${projectTitle(pendingDelete)}” will be removed${
          pendingDelete.freeable_bytes ? `, freeing about ${formatBytes(pendingDelete.freeable_bytes)}` : ""
        }. This can't be undone.` : ""}
        confirmLabel="Delete project"
        pending={remove.isPending}
        error={remove.error?.message ?? null}
        onConfirm={() => pendingDelete && remove.mutate(pendingDelete.id)}
        onCancel={() => { setPendingDelete(null); remove.reset(); }}
      />
    </section>
  );
}
