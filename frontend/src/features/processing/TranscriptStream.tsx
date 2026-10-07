import { motion } from "motion/react";
import { useEffect, useRef, useState, useMemo } from "react";
import { Search, Copy, Check, ChevronDown, ChevronUp, Terminal, Sparkles } from "lucide-react";
import clsx from "clsx";
import { Skeleton } from "../../components/Skeleton";
import { formatTimestamp } from "../../lib/format";
import type { TranscriptLine } from "../../lib/types";

interface Props {
  lines: TranscriptLine[];
  language: string | null;
  live: boolean;
  logs: string[];
  activeRange?: { start: number; end: number } | null;
  className?: string;
  maxHeightClass?: string;
}

export function TranscriptStream({
  lines,
  language,
  live,
  logs,
  activeRange,
  className,
  maxHeightClass = "max-h-[30rem]",
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const activeLineRef = useRef<HTMLLIElement>(null);
  const pinnedToBottom = useRef(true);
  const [search, setSearch] = useState("");
  const [copied, setCopied] = useState(false);
  const [showLogs, setShowLogs] = useState(false);

  // Auto-scroll when live streaming
  useEffect(() => {
    const box = scrollRef.current;
    if (live && box && pinnedToBottom.current) {
      box.scrollTop = box.scrollHeight;
    }
  }, [lines.length, live]);

  // Auto-scroll to active clip range if provided
  useEffect(() => {
    if (activeRange && activeLineRef.current) {
      activeLineRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [activeRange]);

  const filteredLines = useMemo(() => {
    if (!search.trim()) return lines;
    const q = search.toLowerCase();
    return lines.filter((l) => l.text.toLowerCase().includes(q));
  }, [lines, search]);

  const handleCopy = () => {
    const fullText = lines.map((l) => `[${formatTimestamp(l.start)}] ${l.text}`).join("\n");
    void navigator.clipboard.writeText(fullText).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <section className={clsx("rounded-2xl border border-border bg-surface p-4 sm:p-5 flex flex-col shadow-sm", className)}>
      {/* Header */}
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-2.5">
        <div className="flex items-center gap-2">
          <h2 className="font-display text-lg font-semibold tracking-tight">Transcript</h2>
          {language && (
            <span className="rounded-full bg-surface-2 px-2.5 py-0.5 text-[11px] font-medium uppercase tracking-wider text-muted">
              {language}
            </span>
          )}
          {lines.length > 0 && (
            <span className="text-xs text-muted">· {lines.length} segments</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {logs.length > 0 && (
            <button
              type="button"
              onClick={() => setShowLogs((v) => !v)}
              className={clsx(
                "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium transition",
                showLogs ? "bg-gold/20 text-gold" : "bg-surface-2 text-muted hover:text-fg"
              )}
              title="Toggle Pipeline Activity Logs"
            >
              <Terminal className="size-3" />
              <span>Logs ({logs.length})</span>
              {showLogs ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
            </button>
          )}

          {lines.length > 0 && (
            <button
              type="button"
              onClick={handleCopy}
              className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-1 text-xs text-muted transition hover:bg-surface-3 hover:text-fg"
              title="Copy full transcript"
            >
              {copied ? <Check className="size-3 text-green-400" /> : <Copy className="size-3" />}
              <span>{copied ? "Copied" : "Copy"}</span>
            </button>
          )}
        </div>
      </div>

      {/* Activity / Notice logs */}
      {logs.length > 0 && (
        <div className="mb-3 space-y-1.5">
          {logs.map((log) => (
            <p
              key={log}
              className="rounded-xl border border-gold/20 bg-gold/10 px-3.5 py-2 text-xs text-gold leading-relaxed font-medium"
            >
              {log}
            </p>
          ))}
        </div>
      )}

      {/* Search Input when transcript has contents */}
      {lines.length > 5 && (
        <div className="relative mb-3">
          <Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search words in transcript…"
            className="w-full rounded-xl border border-border bg-surface-2/60 pl-8 pr-3 py-1.5 text-xs text-fg placeholder:text-muted/60 focus:border-violet-brand/50 focus:outline-none"
          />
          {search && (
            <button
              type="button"
              onClick={() => setSearch("")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] text-muted hover:text-fg"
            >
              Clear
            </button>
          )}
        </div>
      )}

      {/* Active Clip Range Indicator Banner */}
      {activeRange && (
        <div className="mb-2 flex items-center justify-between rounded-lg bg-violet-brand/10 border border-violet-brand/20 px-3 py-1.5 text-xs text-violet-300">
          <span className="flex items-center gap-1.5 font-medium">
            <Sparkles className="size-3.5 text-violet-brand" />
            Showing clip: {formatTimestamp(activeRange.start)} – {formatTimestamp(activeRange.end)}
          </span>
          <span className="text-[11px] text-muted">Highlighted below</span>
        </div>
      )}

      {/* Content Stream Box */}
      {lines.length === 0 ? (
        live ? (
          <div className="space-y-3 py-4" aria-label="Listening">
            {[80, 65, 90].map((w) => (
              <div key={w} style={{ width: `${w}%` }}>
                <Skeleton className="h-4" />
              </div>
            ))}
            <p className="pt-2 text-xs text-muted flex items-center gap-2">
              <span className="inline-block size-2 rounded-full bg-violet-brand animate-ping" />
              Transcribing speech live…
            </p>
          </div>
        ) : (
          <p className="py-6 text-center text-xs text-muted">
            The transcript will appear here as speech is recognised.
          </p>
        )
      ) : (
        <div
          ref={scrollRef}
          onScroll={(e) => {
            const box = e.currentTarget;
            pinnedToBottom.current = box.scrollHeight - box.scrollTop - box.clientHeight < 48;
          }}
          className={clsx("scroll-smooth overflow-y-auto pr-1.5 flex-1", maxHeightClass)}
          data-lenis-prevent
        >
          {filteredLines.length === 0 ? (
            <p className="py-8 text-center text-xs text-muted">
              No lines matching &ldquo;{search}&rdquo;
            </p>
          ) : (
            <ul className="space-y-1.5">
              {filteredLines.map((line, i) => {
                const isFirstHighlighted =
                  activeRange &&
                  line.start >= activeRange.start &&
                  line.start <= activeRange.end &&
                  (!filteredLines[i - 1] || filteredLines[i - 1].start < activeRange.start);

                const isHighlighted =
                  activeRange &&
                  line.start >= activeRange.start - 0.5 &&
                  line.start <= activeRange.end + 0.5;

                return (
                  <motion.li
                    key={`${line.start}-${i}`}
                    ref={isFirstHighlighted ? activeLineRef : undefined}
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    className={clsx(
                      "flex items-start gap-3 rounded-lg px-2.5 py-1.5 text-xs leading-relaxed transition-colors",
                      isHighlighted
                        ? "bg-violet-brand/15 border-l-2 border-violet-brand text-fg font-medium"
                        : "hover:bg-surface-2/60 text-fg/80"
                    )}
                  >
                    <span className="w-11 shrink-0 pt-0.5 font-mono text-[11px] tabular-nums text-muted select-none">
                      {formatTimestamp(line.start)}
                    </span>
                    <span className="flex-1">{line.text}</span>
                  </motion.li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
