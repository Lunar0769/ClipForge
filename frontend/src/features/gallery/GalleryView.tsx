import { useQuery } from "@tanstack/react-query";
import { motion, AnimatePresence } from "motion/react";
import { useState, useRef, useMemo } from "react";
import {
  Check,
  Copy,
  ChevronDown,
  ChevronUp,
  Hash,
  Sparkles,
  TrendingUp,
  MessageCircle,
} from "lucide-react";
import clsx from "clsx";
import type { Clip, SeoPack, SubScores } from "../../lib/types";
import { api } from "../../lib/api";
import { Skeleton } from "../../components/Skeleton";
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

function ScoreRing({ score, size = 60 }: { score: number; size?: number }) {
  const r = size * 0.38;
  const circ = 2 * Math.PI * r;
  const fill = (score / 100) * circ;
  const hue = Math.round((score / 100) * 120);

  return (
    <div className="relative flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,.08)" strokeWidth={size > 60 ? 5 : 4} />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={`hsl(${hue} 70% 55%)`}
          strokeWidth={size > 60 ? 5 : 4}
          strokeLinecap="round"
          strokeDasharray={circ}
          initial={{ strokeDashoffset: circ }}
          animate={{ strokeDashoffset: circ - fill }}
          transition={{ duration: 1, ease: "easeOut" }}
        />
      </svg>
      <span
        className="absolute font-display font-bold leading-none"
        style={{ color: `hsl(${hue} 70% 65%)`, fontSize: size > 60 ? "1rem" : "0.85rem" }}
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
    <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
      {(Object.entries(SUB_LABELS) as [keyof SubScores, string][]).map(([key, label]) => (
        <div key={key} className="flex items-center gap-2">
          <span className="w-11 text-muted shrink-0 text-[11px]">{label}</span>
          <div className="flex-1 h-1.5 rounded-full bg-surface-2 overflow-hidden">
            <motion.div
              className="h-full rounded-full bg-gradient-to-r from-violet-brand to-cyan-brand"
              initial={{ width: 0 }}
              animate={{ width: `${scores[key]}%` }}
              transition={{ duration: 0.6, ease: "easeOut" }}
            />
          </div>
          <span className="w-5 text-right tabular-nums text-muted text-[10px]">{scores[key]}</span>
        </div>
      ))}
    </div>
  );
}

// ── Copy button ────────────────────────────────────────────────────────────────

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
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
        "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium transition-all",
        copied
          ? "bg-green-500/20 text-green-400"
          : "bg-surface-2 text-muted hover:bg-surface-3 hover:text-fg"
      )}
    >
      {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
      {copied ? "Copied" : label}
    </button>
  );
}

// ── SEO section ────────────────────────────────────────────────────────────────

function SeoSection({ seo }: { seo: SeoPack }) {
  const platforms = [
    { label: "YouTube Shorts", icon: YouTubeIcon, text: seo.youtube_caption, color: "text-red-400" },
    { label: "TikTok", icon: MessageCircle, text: seo.tiktok_caption, color: "text-pink-400" },
    { label: "Reels", icon: InstagramIcon, text: seo.reels_caption, color: "text-purple-400" },
  ];

  return (
    <div className="rounded-xl border border-border bg-surface-2/40 p-3 space-y-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-muted">
        <Hash className="size-3.5 text-violet-brand" />
        <span>Platform Captions & SEO</span>
      </div>

      <div className="space-y-2.5">
        {platforms.map(({ label, icon: Icon, text, color }) => (
          <div key={label} className="rounded-lg bg-surface p-2.5 border border-border/60">
            <div className="mb-1.5 flex items-center justify-between">
              <span className={clsx("flex items-center gap-1.5 text-[11px] font-medium", color)}>
                <Icon className="size-3" />
                {label}
              </span>
              <CopyButton text={text} label="Copy" />
            </div>
            <p className="text-xs leading-relaxed text-fg/85 line-clamp-3 hover:line-clamp-none transition-all">{text}</p>
          </div>
        ))}

        {seo.hashtags.length > 0 && (
          <div className="rounded-lg bg-surface p-2.5 border border-border/60">
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-[11px] font-medium text-muted">{seo.hashtags.length} Hashtags</span>
              <CopyButton
                text={seo.hashtags.map((h) => `#${h}`).join(" ")}
                label="Copy hashtags"
              />
            </div>
            <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
              {seo.hashtags.map((tag) => (
                <span
                  key={tag}
                  className="rounded-md bg-violet-brand/10 px-2 py-0.5 text-[10px] text-violet-brand"
                >
                  #{tag}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Clip Card ──────────────────────────────────────────────────────────────────

interface ClipCardProps {
  clip: Clip;
  index: number;
  isSelected?: boolean;
  onSelect?: () => void;
}

function ClipCard({ clip, index, isSelected, onSelect }: ClipCardProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <motion.article
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.04, 0.4), duration: 0.3 }}
      onClick={onSelect}
      className={clsx(
        "group relative flex flex-col justify-between rounded-2xl border bg-surface p-4 transition-all duration-200 cursor-pointer shadow-sm",
        isSelected
          ? "border-violet-brand ring-1 ring-violet-brand shadow-violet-brand/10"
          : "border-border hover:border-violet-brand/50 hover:shadow-md hover:shadow-violet-brand/5"
      )}
    >
      <div>
        {/* Top Header: Rank, Duration, Virality Score */}
        <div className="flex items-start justify-between gap-3 mb-2.5">
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-0.5 text-[11px] font-semibold text-fg/90">
              <TrendingUp className="size-3 text-violet-brand" />
              #{clip.rank + 1}
            </span>
            <span className="font-mono text-xs text-muted">
              {fmtDuration(clip.start_s, clip.end_s)}
            </span>
          </div>

          <ScoreRing score={clip.score} size={48} />
        </div>

        {/* Title */}
        <h3 className="font-display text-base font-semibold leading-snug tracking-tight text-fg group-hover:text-violet-300 transition-colors">
          {clip.title}
        </h3>

        {/* Viral Reason */}
        <p className="mt-1 text-xs text-muted line-clamp-2 leading-relaxed">
          {clip.why_viral}
        </p>

        {/* Hook Card */}
        {clip.hook_text && (
          <div className="mt-2.5 flex items-start gap-2 rounded-xl border border-violet-brand/20 bg-violet-brand/5 px-2.5 py-2">
            <Sparkles className="mt-0.5 size-3.5 shrink-0 text-violet-brand" />
            <p className="text-xs italic text-fg/90 leading-snug">&ldquo;{clip.hook_text}&rdquo;</p>
          </div>
        )}

        {/* Keywords + Emoji */}
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {clip.emoji.map((e) => (
            <span key={e} className="text-sm leading-none">{e}</span>
          ))}
          {clip.keywords.slice(0, 4).map((kw) => (
            <span
              key={kw}
              className="rounded-md border border-border/80 bg-surface-2/40 px-2 py-0.5 text-[10px] text-muted"
            >
              {kw}
            </span>
          ))}
        </div>
      </div>

      {/* Footer Controls */}
      <div className="mt-3.5 pt-3 border-t border-border/60 flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded((v) => !v);
          }}
          className="inline-flex items-center gap-1 text-xs text-muted hover:text-fg transition font-medium"
        >
          {expanded ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          <span>{expanded ? "Hide Details" : "SEO & Sub-scores"}</span>
        </button>

        <span className="text-[11px] text-violet-400 font-medium group-hover:underline">
          {isSelected ? "Active clip" : "Focus clip →"}
        </span>
      </div>

      {/* Expandable Section */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            key="detail"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="mt-3 pt-3 border-t border-border space-y-3 overflow-hidden text-left"
            onClick={(e) => e.stopPropagation()}
          >
            <SubScoreBars scores={clip.sub_scores} />

            {clip.payoff_summary && (
              <p className="text-xs text-muted">
                <span className="font-medium text-fg">Payoff: </span>
                {clip.payoff_summary}
              </p>
            )}

            {clip.seo && <SeoSection seo={clip.seo} />}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.article>
  );
}

// ── Gallery View Main ──────────────────────────────────────────────────────────

interface GalleryViewProps {
  project: Project;
  activeClipId?: string | null;
  onSelectClip?: (clip: Clip) => void;
  isCompactGrid?: boolean;
}

export default function GalleryView({
  project,
  activeClipId,
  onSelectClip,
  isCompactGrid = false,
}: GalleryViewProps) {
  const [filter, setFilter] = useState<"all" | "high" | "short">("all");

  const { data: clips, isLoading, isError } = useQuery({
    queryKey: ["clips", project.id],
    queryFn: () => api.listClips(project.id),
    staleTime: 30_000,
  });

  const filteredClips = useMemo(() => {
    if (!clips) return [];
    if (filter === "high") return clips.filter((c) => c.score >= 80);
    if (filter === "short") return clips.filter((c) => (c.end_s - c.start_s) <= 45);
    return clips;
  }, [clips, filter]);

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-52 rounded-2xl" />
        ))}
      </div>
    );
  }

  if (isError || !clips) {
    return (
      <div className="rounded-2xl border border-border bg-surface p-6 text-center text-sm text-muted">
        Could not load clips. Make sure the scoring stage completed.
      </div>
    );
  }

  if (clips.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-border py-14 text-center">
        <Sparkles className="mx-auto mb-3 size-8 text-muted" />
        <p className="text-sm font-medium">No clips found yet.</p>
        <p className="mt-1 text-xs text-muted">
          Make sure an LLM key is configured in <code>.env</code> and retry the job.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header and Filter Chips */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-[0.2em] text-muted">Viral Hub</span>
            <span className="rounded-full bg-violet-brand/15 px-2 py-0.5 text-xs font-medium text-violet-300">
              {clips.length} moments
            </span>
          </div>
          <h2 className="mt-0.5 font-display text-xl font-semibold">Ranked Clip Candidates</h2>
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1.5 rounded-full border border-border bg-surface p-1 text-xs">
          <button
            type="button"
            onClick={() => setFilter("all")}
            className={clsx(
              "rounded-full px-3 py-1 font-medium transition",
              filter === "all" ? "bg-violet-brand text-white shadow-sm" : "text-muted hover:text-fg"
            )}
          >
            All ({clips.length})
          </button>
          <button
            type="button"
            onClick={() => setFilter("high")}
            className={clsx(
              "rounded-full px-3 py-1 font-medium transition",
              filter === "high" ? "bg-violet-brand text-white shadow-sm" : "text-muted hover:text-fg"
            )}
          >
            Score 80+ ({clips.filter((c) => c.score >= 80).length})
          </button>
          <button
            type="button"
            onClick={() => setFilter("short")}
            className={clsx(
              "rounded-full px-3 py-1 font-medium transition",
              filter === "short" ? "bg-violet-brand text-white shadow-sm" : "text-muted hover:text-fg"
            )}
          >
            &le;45s ({clips.filter((c) => (c.end_s - c.start_s) <= 45).length})
          </button>
        </div>
      </div>

      {/* Responsive Box Grid Layout */}
      <div className={clsx("grid gap-4", isCompactGrid ? "grid-cols-1 md:grid-cols-2" : "grid-cols-1 md:grid-cols-2 xl:grid-cols-2")}>
        {filteredClips.map((clip, i) => (
          <ClipCard
            key={clip.id}
            clip={clip}
            index={i}
            isSelected={activeClipId === clip.id}
            onSelect={() => onSelectClip?.(clip)}
          />
        ))}
      </div>
    </div>
  );
}
