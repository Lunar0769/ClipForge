import { useQuery } from "@tanstack/react-query";
import { motion, AnimatePresence } from "motion/react";
import { useState, useRef } from "react";
import { Check, Copy, ChevronDown, ChevronUp, Hash, Sparkles, TrendingUp, MessageCircle } from "lucide-react";
import clsx from "clsx";
import type { Clip, SeoPack, SubScores } from "../../lib/types";
import { api } from "../../lib/api";
import { Skeleton } from "../../components/Skeleton";
import { PageTransition } from "../../components/PageTransition";
import type { Project } from "../../lib/types";

function YouTubeIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z" />
    </svg>
  );
}

function InstagramIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <rect width="20" height="20" x="2" y="2" rx="5" ry="5" />
      <path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z" />
      <line x1="17.5" x2="17.51" y1="6.5" y2="6.5" />
    </svg>
  );
}

// ── helpers ────────────────────────────────────────────────────────────────────

function fmtTime(s: number) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

function fmtDuration(start: number, end: number) {
  return `${fmtTime(start)} – ${fmtTime(end)} · ${Math.round(end - start)}s`;
}

// ── Score ring ─────────────────────────────────────────────────────────────────

function ScoreRing({ score }: { score: number }) {
  const r = 28;
  const circ = 2 * Math.PI * r;
  const fill = (score / 100) * circ;
  const hue = Math.round((score / 100) * 120); // 0→red, 120→green

  return (
    <div className="relative flex items-center justify-center" style={{ width: 72, height: 72 }}>
      <svg width={72} height={72} className="-rotate-90">
        <circle cx={36} cy={36} r={r} fill="none" stroke="rgba(255,255,255,.08)" strokeWidth={6} />
        <motion.circle
          cx={36} cy={36} r={r}
          fill="none"
          stroke={`hsl(${hue} 70% 55%)`}
          strokeWidth={6}
          strokeLinecap="round"
          strokeDasharray={circ}
          initial={{ strokeDashoffset: circ }}
          animate={{ strokeDashoffset: circ - fill }}
          transition={{ duration: 1.2, ease: "easeOut" }}
        />
      </svg>
      <span
        className="absolute font-display text-lg font-bold"
        style={{ color: `hsl(${hue} 70% 65%)` }}
      >
        {score}
      </span>
    </div>
  );
}

// ── Sub-score bars ─────────────────────────────────────────────────────────────

const SUB_LABELS: Record<keyof SubScores, string> = {
  hook: "Hook",
  emotion: "Emotion",
  novelty: "Novelty",
  value: "Value",
  shareability: "Share",
  loop_potential: "Loop",
};

function SubScoreBars({ scores }: { scores: SubScores }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
      {(Object.entries(SUB_LABELS) as [keyof SubScores, string][]).map(([key, label]) => (
        <div key={key} className="flex items-center gap-2">
          <span className="w-12 text-muted shrink-0">{label}</span>
          <div className="flex-1 h-1.5 rounded-full bg-surface-2 overflow-hidden">
            <motion.div
              className="h-full rounded-full bg-gradient-to-r from-violet-brand to-cyan-brand"
              initial={{ width: 0 }}
              animate={{ width: `${scores[key]}%` }}
              transition={{ duration: 0.8, ease: "easeOut", delay: 0.2 }}
            />
          </div>
          <span className="w-6 text-right tabular-nums text-muted">{scores[key]}</span>
        </div>
      ))}
    </div>
  );
}

// ── Copy button ────────────────────────────────────────────────────────────────

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleCopy = () => {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-all",
        copied
          ? "bg-green-500/20 text-green-400"
          : "bg-surface-2 text-muted hover:bg-surface-3 hover:text-fg",
      )}
    >
      {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
      {copied ? "Copied!" : label}
    </button>
  );
}

// ── SEO accordion ─────────────────────────────────────────────────────────────

function SeoSection({ seo }: { seo: SeoPack }) {
  const [open, setOpen] = useState(false);

  const platforms = [
    { label: "YouTube Shorts", icon: YouTubeIcon, text: seo.youtube_caption, color: "text-red-400" },
    { label: "TikTok", icon: MessageCircle, text: seo.tiktok_caption, color: "text-pink-400" },
    { label: "Reels", icon: InstagramIcon, text: seo.reels_caption, color: "text-purple-400" },
  ];

  return (
    <div className="rounded-xl border border-border bg-surface">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium"
      >
        <span className="flex items-center gap-2 text-muted">
          <Hash className="size-4 text-violet-brand" />
          SEO Pack · captions + hashtags
        </span>
        {open ? <ChevronUp className="size-4 text-muted" /> : <ChevronDown className="size-4 text-muted" />}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            key="seo"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="space-y-4 px-4 pb-4">
              {platforms.map(({ label, icon: Icon, text, color }) => (
                <div key={label}>
                  <div className="mb-1.5 flex items-center justify-between">
                    <span className={clsx("flex items-center gap-1.5 text-xs font-medium", color)}>
                      <Icon className="size-3.5" />
                      {label}
                    </span>
                    <CopyButton text={text} label="Copy caption" />
                  </div>
                  <p className="rounded-lg bg-surface-2 px-3 py-2 text-sm leading-relaxed text-fg/80">{text}</p>
                </div>
              ))}

              {seo.hashtags.length > 0 && (
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-medium text-muted">{seo.hashtags.length} hashtags</span>
                    <CopyButton
                      text={seo.hashtags.map((h) => `#${h}`).join(" ")}
                      label="Copy all"
                    />
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {seo.hashtags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded-full bg-violet-brand/10 px-2.5 py-0.5 text-xs text-violet-brand"
                      >
                        #{tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {seo.cta && (
                <div>
                  <div className="mb-1.5 flex items-center justify-between">
                    <span className="text-xs font-medium text-muted">CTA</span>
                    <CopyButton text={seo.cta} label="Copy CTA" />
                  </div>
                  <p className="rounded-lg bg-surface-2 px-3 py-2 text-sm text-fg/80">{seo.cta}</p>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Clip card ─────────────────────────────────────────────────────────────────

function ClipCard({ clip, index }: { clip: Clip; index: number }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <motion.article
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06, duration: 0.4 }}
      className="group relative flex flex-col gap-4 rounded-2xl border border-border bg-surface p-5 shadow-sm transition hover:border-violet-brand/40 hover:shadow-violet-brand/5"
    >
      {/* Rank badge */}
      <div className="absolute right-5 top-5 flex items-center gap-1 text-xs text-muted">
        <TrendingUp className="size-3" />
        #{clip.rank + 1}
      </div>

      {/* Header */}
      <div className="flex items-start gap-4 pr-8">
        <ScoreRing score={clip.score} />
        <div className="min-w-0 flex-1">
          <p className="text-xs text-muted">{fmtDuration(clip.start_s, clip.end_s)}</p>
          <h3 className="mt-0.5 font-display text-lg font-semibold leading-snug">{clip.title}</h3>
          <p className="mt-1 text-sm text-muted">{clip.why_viral}</p>
        </div>
      </div>

      {/* Hook pill */}
      {clip.hook_text && (
        <div className="flex items-start gap-2 rounded-xl border border-violet-brand/20 bg-violet-brand/5 px-3 py-2">
          <Sparkles className="mt-0.5 size-3.5 shrink-0 text-violet-brand" />
          <p className="text-sm italic text-fg/80">&ldquo;{clip.hook_text}&rdquo;</p>
        </div>
      )}

      {/* Keywords + emoji */}
      <div className="flex flex-wrap items-center gap-1.5">
        {clip.emoji.map((e) => (
          <span key={e} className="text-lg leading-none">{e}</span>
        ))}
        {clip.keywords.map((kw) => (
          <span
            key={kw}
            className="rounded-full border border-border px-2.5 py-0.5 text-xs text-muted"
          >
            {kw}
          </span>
        ))}
      </div>

      {/* Expand toggle */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1.5 self-start text-xs text-muted transition hover:text-fg"
      >
        {expanded ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
        {expanded ? "Less detail" : "Sub-scores & SEO pack"}
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            key="detail"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="space-y-4 overflow-hidden"
          >
            <SubScoreBars scores={clip.sub_scores} />
            {clip.payoff_summary && (
              <p className="text-sm text-muted">
                <span className="font-medium text-fg">Payoff: </span>
                {clip.payoff_summary}
              </p>
            )}
            {clip.seo && Object.values(clip.seo).some((v) => (Array.isArray(v) ? v.length : v)) && (
              <SeoSection seo={clip.seo} />
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.article>
  );
}

// ── Gallery page ──────────────────────────────────────────────────────────────

interface GalleryViewProps {
  project: Project;
}

export default function GalleryView({ project }: GalleryViewProps) {
  const { data: clips, isLoading, isError } = useQuery({
    queryKey: ["clips", project.id],
    queryFn: () => api.listClips(project.id),
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-48 rounded-2xl" />
        ))}
      </div>
    );
  }

  if (isError || !clips) {
    return (
      <p className="text-sm text-muted">
        Could not load clips. Make sure the scoring stage completed.
      </p>
    );
  }

  if (clips.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-border py-16 text-center">
        <Sparkles className="mx-auto mb-3 size-8 text-muted" />
        <p className="text-sm font-medium">No clips found yet.</p>
        <p className="mt-1 text-xs text-muted">
          Make sure an LLM key is configured in <code>.env</code> and retry the job.
        </p>
      </div>
    );
  }

  return (
    <PageTransition>
      <div className="space-y-5">
        <header className="flex items-end justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-muted">Clips</p>
            <h2 className="mt-1 font-display text-2xl font-semibold">
              {clips.length} viral moment{clips.length !== 1 ? "s" : ""} found
            </h2>
          </div>
          <p className="text-xs text-muted">Ranked by virality score</p>
        </header>
        <div className="space-y-4">
          {clips.map((clip, i) => (
            <ClipCard key={clip.id} clip={clip} index={i} />
          ))}
        </div>
      </div>
    </PageTransition>
  );
}
