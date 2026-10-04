import { motion } from "motion/react";
import { useEffect, useRef } from "react";
import { Skeleton } from "../../components/Skeleton";
import { formatTimestamp } from "../../lib/format";
import type { TranscriptLine } from "../../lib/types";

interface Props {
  lines: TranscriptLine[];
  language: string | null;
  live: boolean;
  logs: string[];
}

export function TranscriptStream({ lines, language, live, logs }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedToBottom = useRef(true);
  // Follow new lines inside the transcript box only (never scroll the page),
  // and only while the reader hasn't scrolled up to read earlier lines.
  useEffect(() => {
    const box = scrollRef.current;
    if (live && box && pinnedToBottom.current) box.scrollTop = box.scrollHeight;
  }, [lines.length, live]);

  return (
    <section className="mt-10 rounded-3xl border border-border bg-surface p-5 sm:p-6">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="font-display text-xl font-semibold">Transcript</h2>
        <div className="flex items-center gap-2 text-xs text-muted">
          {language && <span className="rounded-full bg-surface-2 px-3 py-1 uppercase tracking-wider">{language}</span>}
          {lines.length > 0 && <span>{lines.length} segments</span>}
        </div>
      </div>
      {logs.map((log) => (
        <p key={log} className="mb-3 rounded-xl bg-gold/10 px-4 py-2 text-sm text-gold">{log}</p>
      ))}
      {lines.length === 0 ? (
        live ? (
          <div className="space-y-3" aria-label="Listening">
            {[80, 65, 90].map((w) => (
              <div key={w} style={{ width: `${w}%` }}>
                <Skeleton className="h-4" />
              </div>
            ))}
            <p className="pt-2 text-sm text-muted">Listening…</p>
          </div>
        ) : (
          <p className="text-sm text-muted">The transcript will appear here as speech is recognised.</p>
        )
      ) : (
        <div
          ref={scrollRef}
          onScroll={(e) => {
            const box = e.currentTarget;
            pinnedToBottom.current = box.scrollHeight - box.scrollTop - box.clientHeight < 48;
          }}
          className="max-h-[28rem] scroll-smooth overflow-y-auto pr-2"
          data-lenis-prevent
        >
          <ul className="space-y-2">
            {lines.map((line, i) => (
              <motion.li
                key={`${line.start}-${i}`}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex gap-4 text-sm leading-relaxed"
              >
                <span className="w-12 shrink-0 pt-0.5 font-mono text-xs tabular-nums text-muted">{formatTimestamp(line.start)}</span>
                <span>{line.text}</span>
              </motion.li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
