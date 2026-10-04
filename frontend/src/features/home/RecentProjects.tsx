import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { Link } from "react-router";
import { Skeleton } from "../../components/Skeleton";
import { StatusChip } from "../../components/StatusChip";
import { api } from "../../lib/api";
import { formatDuration, formatRelative, projectTitle } from "../../lib/format";

export function RecentProjects() {
  const { data, isLoading } = useQuery({ queryKey: ["projects"], queryFn: api.listProjects });

  if (isLoading) {
    return (
      <section className="mx-auto grid max-w-6xl gap-4 px-4 pb-24 sm:grid-cols-2 sm:px-6 lg:grid-cols-3">
        {[0, 1, 2].map((i) => <Skeleton key={i} className="h-28 rounded-2xl" />)}
      </section>
    );
  }
  if (!data?.length) return null;

  return (
    <section className="mx-auto max-w-6xl px-4 pb-24 sm:px-6">
      <h2 className="mb-6 font-display text-2xl font-semibold tracking-tight">Recent projects</h2>
      <motion.ul
        initial="hidden"
        animate="show"
        variants={{ show: { transition: { staggerChildren: 0.06 } } }}
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      >
        {data.slice(0, 9).map((project) => (
          <motion.li key={project.id} className="min-w-0" variants={{ hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0 } }}>
            <Link
              to={`/projects/${project.id}`}
              className="group block h-full rounded-2xl border border-border bg-surface p-5 transition hover:-translate-y-0.5 hover:border-violet-brand/50 hover:bg-surface-2"
            >
              <div className="flex items-start justify-between gap-3">
                <span className="line-clamp-2 min-w-0 font-medium [overflow-wrap:anywhere]">{projectTitle(project)}</span>
                {project.latest_job && <StatusChip status={project.latest_job.status} />}
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                <span>{project.source_type === "url" ? "Link" : "Upload"}</span>
                {project.duration_s != null && <span>{formatDuration(project.duration_s)}</span>}
                <span>{formatRelative(project.created_at)}</span>
              </div>
            </Link>
          </motion.li>
        ))}
      </motion.ul>
    </section>
  );
}
