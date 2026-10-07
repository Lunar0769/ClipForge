import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, useSpring, useTransform } from "motion/react";
import { useEffect, useState } from "react";
import { useParams } from "react-router";
import { Columns2, LayoutGrid, FileText, CheckCircle2 } from "lucide-react";
import clsx from "clsx";
import { NotFound } from "../../components/NotFound";
import { PageTransition } from "../../components/PageTransition";
import { Skeleton } from "../../components/Skeleton";
import { StatusChip } from "../../components/StatusChip";
import { api } from "../../lib/api";
import { projectTitle } from "../../lib/format";
import { estimateEtaFromBaseline, formatEta, type EtaBaseline, overallProgress, stagesFromJob } from "../../lib/progress";
import { isTerminal, type JobStatus, type Clip } from "../../lib/types";
import { useNow } from "../../lib/useNow";
import { ErrorPanel } from "./ErrorPanel";
import { PipelineConstellation } from "./PipelineConstellation";
import { TranscriptStream } from "./TranscriptStream";
import { useJobEvents } from "./useJobEvents";
import GalleryView from "../gallery/GalleryView";

const NO_SPEECH = "No speech was detected in this video.";

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

  const [activeClip, setActiveClip] = useState<Clip | null>(null);
  const [viewMode, setViewMode] = useState<"split" | "clips" | "transcript">("split");

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
  const stages = stagesQuery.data ?? [];
  const stageStates = Object.keys(view.stages).length || !job ? view.stages : stagesFromJob(stages, job);
  const progress = overallProgress(stages, { jobStatus: status ?? null, stages: stageStates });
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
      <div className="mx-auto max-w-7xl space-y-4 px-4 py-14 sm:px-6">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-28" />
      </div>
    );
  }

  const eta = estimateEtaFromBaseline(baseline, now, progress);
  const saved = status === "succeeded" ? transcriptQuery.data : undefined;
  const lines = saved ? saved.segments : view.transcript;
  const logs = saved && saved.segments.length === 0 && !view.logs.includes(NO_SPEECH)
    ? [...view.logs, NO_SPEECH]
    : view.logs;
  const active = status === "running" || status === "queued";
  const isSucceeded = status === "succeeded";

  return (
    <PageTransition>
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10">
        {/* Header */}
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-[0.2em] text-muted">Project Studio</span>
              {isSucceeded && (
                <span className="inline-flex items-center gap-1 rounded-full bg-green-500/10 px-2 py-0.5 text-[11px] font-medium text-green-400">
                  <CheckCircle2 className="size-3" />
                  Ready
                </span>
              )}
            </div>
            <h1 className="mt-1.5 truncate font-display text-2xl font-semibold tracking-tight sm:text-3xl text-fg">
              {projectTitle(project)}
            </h1>
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

        <PipelineConstellation stages={stages} state={stageStates} />

        {/* Errors / Cancellation */}
        {status === "failed" && (
          <ErrorPanel
            title="Something went wrong"
            message={view.error ?? job?.error ?? null}
            hint={view.hint ?? job?.error_hint ?? null}
            onRetry={() => retry.mutate()}
            pending={retry.isPending}
          />
        )}
        {(retry.error || cancel.error) && (
          <p role="alert" className="mt-4 text-sm text-red-400">
            {((retry.error ?? cancel.error) as Error).message}
          </p>
        )}
        {status === "cancelled" && (
          <ErrorPanel
            title="Cancelled"
            message="This job was cancelled."
            hint={null}
            onRetry={() => retry.mutate()}
            pending={retry.isPending}
          />
        )}

        {/* WORKBENCH CONTENT */}
        {!isSucceeded ? (
          /* Live processing mode: simple vertical stream */
          <div className="mt-8">
            <TranscriptStream
              lines={lines}
              language={view.language ?? transcriptQuery.data?.language ?? null}
              live={status === "running"}
              logs={logs}
            />
          </div>
        ) : (
          /* Succeeded mode: PRO STUDIO BOX LAYOUT */
          <div className="mt-6 space-y-4">
            {/* Studio View Switcher Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-surface p-2">
              <div className="flex items-center gap-1 text-xs">
                <button
                  type="button"
                  onClick={() => setViewMode("split")}
                  className={clsx(
                    "inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 font-medium transition",
                    viewMode === "split"
                      ? "bg-violet-brand text-white shadow-sm"
                      : "text-muted hover:text-fg hover:bg-surface-2"
                  )}
                >
                  <Columns2 className="size-3.5" />
                  <span className="hidden sm:inline">Studio Workbench</span>
                  <span className="sm:hidden">Split</span>
                </button>

                <button
                  type="button"
                  onClick={() => setViewMode("clips")}
                  className={clsx(
                    "inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 font-medium transition",
                    viewMode === "clips"
                      ? "bg-violet-brand text-white shadow-sm"
                      : "text-muted hover:text-fg hover:bg-surface-2"
                  )}
                >
                  <LayoutGrid className="size-3.5" />
                  <span>Clips Grid</span>
                </button>

                <button
                  type="button"
                  onClick={() => setViewMode("transcript")}
                  className={clsx(
                    "inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 font-medium transition",
                    viewMode === "transcript"
                      ? "bg-violet-brand text-white shadow-sm"
                      : "text-muted hover:text-fg hover:bg-surface-2"
                  )}
                >
                  <FileText className="size-3.5" />
                  <span>Transcript</span>
                </button>
              </div>

              <div className="text-xs text-muted pr-2 hidden md:block">
                Click any clip to focus & jump to its spoken transcript
              </div>
            </div>

            {/* Layout Panels */}
            {viewMode === "split" && (
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
                {/* Left Box: Viral Clips Grid (7 Cols) */}
                <div className="lg:col-span-7 space-y-4">
                  <GalleryView
                    project={project}
                    activeClipId={activeClip?.id}
                    onSelectClip={setActiveClip}
                    isCompactGrid
                  />
                </div>

                {/* Right Box: Sticky Inspector Transcript Box (5 Cols) */}
                <div className="lg:col-span-5 lg:sticky lg:top-6">
                  <TranscriptStream
                    lines={lines}
                    language={view.language ?? transcriptQuery.data?.language ?? null}
                    live={false}
                    logs={logs}
                    activeRange={activeClip ? { start: activeClip.start_s, end: activeClip.end_s } : null}
                    maxHeightClass="max-h-[38rem]"
                  />
                </div>
              </div>
            )}

            {viewMode === "clips" && (
              <div>
                <GalleryView
                  project={project}
                  activeClipId={activeClip?.id}
                  onSelectClip={setActiveClip}
                />
              </div>
            )}

            {viewMode === "transcript" && (
              <div>
                <TranscriptStream
                  lines={lines}
                  language={view.language ?? transcriptQuery.data?.language ?? null}
                  live={false}
                  logs={logs}
                  activeRange={activeClip ? { start: activeClip.start_s, end: activeClip.end_s } : null}
                  maxHeightClass="max-h-[46rem]"
                />
              </div>
            )}
          </div>
        )}
      </div>
    </PageTransition>
  );
}
