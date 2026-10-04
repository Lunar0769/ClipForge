import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, useSpring, useTransform } from "motion/react";
import { useEffect, useState } from "react";
import { useParams } from "react-router";
import { NotFound } from "../../components/NotFound";
import { PageTransition } from "../../components/PageTransition";
import { Skeleton } from "../../components/Skeleton";
import { StatusChip } from "../../components/StatusChip";
import { api } from "../../lib/api";
import { projectTitle } from "../../lib/format";
import { estimateEtaFromBaseline, formatEta, type EtaBaseline, overallProgress } from "../../lib/progress";
import { isTerminal, type JobStatus } from "../../lib/types";
import { useNow } from "../../lib/useNow";
import { ErrorPanel } from "./ErrorPanel";
import { PipelineConstellation } from "./PipelineConstellation";
import { TranscriptStream } from "./TranscriptStream";
import { useJobEvents } from "./useJobEvents";

function AnimatedPercent({ value }: { value: number }) {
  const spring = useSpring(value, { stiffness: 120, damping: 20 });
  const text = useTransform(spring, (v) => `${Math.round(v * 100)}%`);
  useEffect(() => spring.set(value), [spring, value]);
  return <motion.span>{text}</motion.span>;
}

export default function ProcessingPage() {
  const { projectId = "" } = useParams();
  const queryClient = useQueryClient();
  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
    refetchInterval: (q) => (isTerminal(q.state.data?.latest_job?.status) ? false : 4000),
  });
  const stagesQuery = useQuery({ queryKey: ["stages"], queryFn: api.stages, staleTime: Infinity });
  const job = projectQuery.data?.latest_job ?? null;
  const view = useJobEvents(job?.id);
  const status: JobStatus | undefined = view.jobStatus ?? job?.status;

  useEffect(() => {
    if (isTerminal(view.jobStatus)) {
      void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    }
  }, [view.jobStatus, projectId, queryClient]);

  const transcriptQuery = useQuery({
    queryKey: ["transcript", projectId],
    queryFn: () => api.transcript(projectId),
    enabled: status === "succeeded",
  });
  const retry = useMutation({
    mutationFn: () => api.retry(projectId),
    onSuccess: (project) => queryClient.setQueryData(["project", projectId], project),
  });
  const cancel = useMutation({ mutationFn: (jobId: string) => api.cancelJob(jobId) });

  const now = useNow(1000);
  const progress = overallProgress(stagesQuery.data ?? [], view);
  const [baseline, setBaseline] = useState<EtaBaseline | null>(null);
  const jobId = job?.id;
  useEffect(() => setBaseline(null), [jobId]);
  useEffect(() => {
    if (status !== "running") setBaseline(null);
    else if (!baseline || progress < baseline.progress) setBaseline({ t: Date.now(), progress });
  }, [status, progress, baseline]);

  if (projectQuery.isError) return <NotFound message="We couldn't find this project." />;
  const project = projectQuery.data;
  if (!project) {
    return (
      <div className="mx-auto max-w-6xl space-y-4 px-4 py-14 sm:px-6">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-28" />
      </div>
    );
  }

  const stages = stagesQuery.data ?? [];
  const eta = estimateEtaFromBaseline(baseline, now, progress);
  const lines = view.transcript.length ? view.transcript : (transcriptQuery.data?.segments ?? []);
  const active = status === "running" || status === "queued";

  return (
    <PageTransition>
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 sm:py-14">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-[0.2em] text-muted">Project</p>
            <h1 className="mt-2 truncate font-display text-3xl font-semibold tracking-tight sm:text-4xl">{projectTitle(project)}</h1>
          </div>
          <div className="flex items-center gap-3">
            {status && <StatusChip status={status} />}
            {active && job && (
              <button
                type="button"
                onClick={() => cancel.mutate(job.id)}
                disabled={cancel.isPending}
                className="rounded-full border border-border px-4 py-1.5 text-sm text-muted transition hover:bg-surface-2 hover:text-fg"
              >
                Cancel
              </button>
            )}
          </div>
        </header>

        <div className="mt-8">
          <div className="flex items-end justify-between">
            <span className="font-display text-5xl font-semibold tabular-nums text-gradient">
              <AnimatedPercent value={progress} />
            </span>
            <span className="text-sm text-muted">
              {status === "succeeded" ? "Transcript ready" : active ? formatEta(eta) : ""}
            </span>
          </div>
          <div
            role="progressbar"
            aria-label="Overall progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress * 100)}
            className="mt-3 h-2 overflow-hidden rounded-full bg-surface-2"
          >
            <motion.div
              className="h-full origin-left rounded-full bg-gradient-to-r from-violet-brand via-indigo-brand to-cyan-brand"
              animate={{ scaleX: progress }}
              transition={{ type: "spring", stiffness: 60, damping: 18 }}
            />
          </div>
        </div>

        <PipelineConstellation stages={stages} state={view.stages} />

        {status === "failed" && (
          <ErrorPanel
            title="Something went wrong"
            message={view.error ?? job?.error ?? null}
            hint={view.hint ?? job?.error_hint ?? null}
            onRetry={() => retry.mutate()}
            pending={retry.isPending}
          />
        )}
        {(retry.isError || cancel.isError) && (
          <p role="alert" className="mt-4 text-sm text-red-400">
            {((retry.error ?? cancel.error) as Error).message}
          </p>
        )}
        {status === "cancelled" && (
          <ErrorPanel title="Cancelled" message="This job was cancelled." hint={null} onRetry={() => retry.mutate()} pending={retry.isPending} />
        )}

        <TranscriptStream
          lines={lines}
          language={view.language ?? transcriptQuery.data?.language ?? null}
          live={status === "running"}
          logs={view.logs}
        />
      </div>
    </PageTransition>
  );
}
