import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { lazy, Suspense } from "react";
import { useNavigate } from "react-router";
import { PageTransition } from "../../components/PageTransition";
import { StaticGradient } from "../../components/StaticGradient";
import { api } from "../../lib/api";
import type { Project } from "../../lib/types";
import { DropZone } from "./DropZone";
import { HeroHeadline } from "./HeroHeadline";
import { HeroInput } from "./HeroInput";
import { RecentProjects } from "./RecentProjects";

const ShaderBackground = lazy(() => import("../../components/ShaderBackground"));

export default function HomePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const open = (project: Project) => {
    void queryClient.invalidateQueries({ queryKey: ["projects"] });
    navigate(`/projects/${project.id}`);
  };
  const create = useMutation({ mutationFn: (url: string) => api.createFromUrl(url), onSuccess: open });

  return (
    <PageTransition>
      <section className="relative isolate overflow-hidden">
        <div className="absolute inset-0 -z-10">
          <Suspense fallback={<StaticGradient />}>
            <ShaderBackground />
          </Suspense>
          <div className="absolute inset-0 bg-gradient-to-b from-transparent via-bg/30 to-bg" />
        </div>
        <div className="mx-auto flex max-w-4xl flex-col items-center px-4 pb-20 pt-20 text-center sm:px-6 sm:pt-28">
          <motion.span
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-6 inline-flex items-center gap-2 rounded-full border border-border bg-surface px-4 py-1.5 text-xs text-muted backdrop-blur"
          >
            <Sparkles className="size-3.5 text-violet-brand" aria-hidden="true" />
            AI clip studio · runs on your GPU
          </motion.span>
          <HeroHeadline />
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.5 }}
            className="mt-6 max-w-xl text-balance text-base text-muted sm:text-lg"
          >
            Paste a YouTube link or drop a video. ClipForge transcribes it, finds the moments worth sharing and
            cuts them into captioned vertical shorts.
          </motion.p>
          <HeroInput
            className="mt-10"
            pending={create.isPending}
            serverError={create.error?.message ?? null}
            onSubmit={(url) => create.mutate(url)}
          />
          <div className="my-6 flex w-full max-w-2xl items-center gap-4 text-xs uppercase tracking-[0.2em] text-muted">
            <span className="h-px flex-1 bg-border" />or<span className="h-px flex-1 bg-border" />
          </div>
          <DropZone className="w-full max-w-2xl" onUploaded={open} />
        </div>
      </section>
      <RecentProjects />
    </PageTransition>
  );
}
