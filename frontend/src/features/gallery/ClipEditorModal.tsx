import { motion, AnimatePresence } from "motion/react";
import { useState, useRef, useEffect } from "react";
import {
  X,
  Play,
  Pause,
  RefreshCw,
  Sparkles,
  ZoomIn,
  Music,
  Scissors,
  RotateCcw,
  Clock,
  Check,
  AlertCircle,
} from "lucide-react";
import clsx from "clsx";
import type { Clip, Project } from "../../lib/types";
import { api } from "../../lib/api";

interface ClipEditorModalProps {
  clip: Clip;
  project: Project;
  isOpen: boolean;
  onClose: () => void;
  onClipUpdated: (updated: Clip) => void;
}

function fmtSeconds(s: number) {
  const m = Math.floor(s / 60);
  const sec = (s % 60).toFixed(1);
  return `${m}:${parseFloat(sec) < 10 ? "0" : ""}${sec}`;
}

export function ClipEditorModal({
  clip,
  project,
  isOpen,
  onClose,
  onClipUpdated,
}: ClipEditorModalProps) {
  // Local editable state
  const [startS, setStartS] = useState(clip.start_s);
  const [endS, setEndS] = useState(clip.end_s);
  const [title, setTitle] = useState(clip.title);
  const [hookText, setHookText] = useState(clip.hook_text || clip.title);
  const [subtitleStyle, setSubtitleStyle] = useState(clip.subtitle_style || "hormozi");
  const [autoZoom, setAutoZoom] = useState(clip.auto_zoom !== false);
  const [musicMood, setMusicMood] = useState<string | null>(clip.music_mood || null);

  const [isPlaying, setIsPlaying] = useState(false);
  const [isRendering, setIsRendering] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successNotice, setSuccessNotice] = useState(false);
  const [videoKey, setVideoKey] = useState(0);

  const videoRef = useRef<HTMLVideoElement>(null);

  // Sync state when clip prop changes
  useEffect(() => {
    setStartS(clip.start_s);
    setEndS(clip.end_s);
    setTitle(clip.title);
    setHookText(clip.hook_text || clip.title);
    setSubtitleStyle(clip.subtitle_style || "hormozi");
    setAutoZoom(clip.auto_zoom !== false);
    setMusicMood(clip.music_mood || null);
    setErrorMsg(null);
  }, [clip]);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen && !isRendering) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, isRendering, onClose]);

  if (!isOpen) return null;

  const duration = Math.max(0, endS - startS);
  const maxSourceDuration = project.duration_s || Math.max(endS + 60, 180);

  const videoUrl = `${api.clipVideoUrl(clip.id)}?v=${videoKey}`;

  const togglePlay = () => {
    if (!videoRef.current || isRendering) return;
    if (isPlaying) {
      videoRef.current.pause();
      setIsPlaying(false);
    } else {
      void videoRef.current.play();
      setIsPlaying(true);
    }
  };

  const nudgeStart = (delta: number) => {
    const next = Math.max(0, Math.min(startS + delta, endS - 3));
    setStartS(parseFloat(next.toFixed(1)));
  };

  const nudgeEnd = (delta: number) => {
    const next = Math.min(maxSourceDuration, Math.max(endS + delta, startS + 3));
    setEndS(parseFloat(next.toFixed(1)));
  };

  const handleReset = () => {
    setStartS(clip.start_s);
    setEndS(clip.end_s);
    setTitle(clip.title);
    setHookText(clip.hook_text || clip.title);
    setSubtitleStyle(clip.subtitle_style || "hormozi");
    setAutoZoom(clip.auto_zoom !== false);
    setMusicMood(clip.music_mood || null);
    setErrorMsg(null);
  };

  const handleSaveAndRerender = async () => {
    if (duration < 5) {
      setErrorMsg("Short must be at least 5 seconds long.");
      return;
    }
    if (duration > 90) {
      setErrorMsg("Shorts must be under 90 seconds for vertical platforms.");
      return;
    }

    setIsRendering(true);
    setErrorMsg(null);
    setSuccessNotice(false);

    try {
      const updated = await api.rerenderClip(clip.id, {
        subtitleStyle,
        autoZoom,
        musicMood,
        startS,
        endS,
        title,
        hookText,
      });

      setVideoKey((k) => k + 1);
      setIsPlaying(false);
      setSuccessNotice(true);
      onClipUpdated(updated);
      setTimeout(() => setSuccessNotice(false), 2500);
    } catch (err) {
      console.error("Trim and render error:", err);
      setErrorMsg(err instanceof Error ? err.message : "Failed to re-render clip.");
    } finally {
      setIsRendering(false);
    }
  };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-5 overflow-y-auto">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={() => !isRendering && onClose()}
          className="fixed inset-0 bg-black/85 backdrop-blur-md"
        />

        {/* Modal Window */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 15 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 15 }}
          transition={{ duration: 0.2 }}
          className="relative z-10 w-full max-w-4xl max-h-[92vh] flex flex-col rounded-3xl border border-violet-500/20 bg-surface/95 shadow-2xl shadow-violet-brand/10 backdrop-blur-xl overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-border/70 px-5 py-3.5 bg-surface-2/40">
            <div className="flex items-center gap-2.5">
              <span className="flex items-center gap-1.5 rounded-full bg-violet-brand/20 px-3 py-1 text-xs font-semibold text-violet-300">
                <Scissors className="size-3.5" />
                Clip #{clip.rank + 1} Studio Editor
              </span>
              <span className="hidden sm:inline text-xs text-muted truncate max-w-xs font-mono">
                {title}
              </span>
            </div>

            <button
              type="button"
              disabled={isRendering}
              onClick={onClose}
              className="rounded-full p-1.5 text-muted hover:text-fg hover:bg-surface-3 transition"
              aria-label="Close editor"
            >
              <X className="size-4" />
            </button>
          </div>

          {/* Modal Body: Two-column layout */}
          <div className="flex-1 overflow-y-auto p-4 sm:p-6 grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Left Column: 9:16 Video Player & Timeline */}
            <div className="lg:col-span-5 flex flex-col items-center">
              <div className="relative aspect-[9/16] w-full max-w-[260px] rounded-2xl overflow-hidden bg-black shadow-xl border border-border/80 flex items-center justify-center">
                <video
                  ref={videoRef}
                  key={videoUrl}
                  src={videoUrl}
                  playsInline
                  loop
                  onPlay={() => setIsPlaying(true)}
                  onPause={() => setIsPlaying(false)}
                  className="h-full w-full object-contain"
                />

                {/* Loading overlay during re-render */}
                {isRendering && (
                  <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/85 backdrop-blur-sm gap-2.5 p-4 text-center">
                    <RefreshCw className="size-8 animate-spin text-violet-brand" />
                    <span className="text-xs font-semibold text-white">
                      Cutting & re-rendering vertical 9:16 Short...
                    </span>
                    <span className="text-[10px] text-muted">Burning subtitles & audio mix</span>
                  </div>
                )}

                {/* Play/Pause Button */}
                {!isRendering && (
                  <button
                    type="button"
                    onClick={togglePlay}
                    className={clsx(
                      "absolute inset-0 flex items-center justify-center transition-all bg-black/25",
                      isPlaying ? "opacity-0 hover:opacity-100 bg-black/40" : "opacity-100"
                    )}
                    aria-label={isPlaying ? "Pause preview" : "Play preview"}
                  >
                    <div className="flex size-12 items-center justify-center rounded-full bg-violet-brand text-white shadow-lg shadow-violet-brand/50">
                      {isPlaying ? <Pause className="size-6" /> : <Play className="size-6 fill-current ml-0.5" />}
                    </div>
                  </button>
                )}
              </div>

              {/* Quick playback badge */}
              <div className="mt-3 flex items-center gap-2 text-xs font-mono text-muted">
                <Clock className="size-3.5 text-violet-brand" />
                <span>Trim: {fmtSeconds(startS)} → {fmtSeconds(endS)}</span>
                <span className="font-semibold text-fg">({duration.toFixed(1)}s)</span>
              </div>
            </div>

            {/* Right Column: Timeline Controls, Hook Editor, Subtitles & Audio Polish */}
            <div className="lg:col-span-7 flex flex-col space-y-4">
              {/* Timeline Trimming Card */}
              <div className="rounded-2xl border border-border/80 bg-surface-2/40 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted">
                    <Scissors className="size-3.5 text-cyan-brand" />
                    <span>Timeline & Duration</span>
                  </div>
                  <span
                    className={clsx(
                      "rounded-full px-2.5 py-0.5 text-[11px] font-semibold",
                      duration >= 20 && duration <= 60
                        ? "bg-emerald-500/15 text-emerald-300"
                        : "bg-amber-500/15 text-amber-300"
                    )}
                  >
                    {duration.toFixed(1)}s · {duration >= 20 && duration <= 60 ? "Optimal Hook Duration" : "Custom Length"}
                  </span>
                </div>

                {/* Start Trim Control */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted font-medium">Start Boundary:</span>
                    <span className="font-mono text-fg font-semibold">{fmtSeconds(startS)}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      disabled={isRendering}
                      onClick={() => nudgeStart(-0.5)}
                      className="rounded-lg bg-surface border border-border px-2 py-1 text-xs font-mono text-muted hover:text-fg hover:bg-surface-3 transition"
                    >
                      -0.5s
                    </button>
                    <input
                      type="range"
                      min={0}
                      max={Math.max(0, endS - 3)}
                      step={0.1}
                      value={startS}
                      disabled={isRendering}
                      onChange={(e) => setStartS(parseFloat(e.target.value))}
                      className="flex-1 accent-cyan-brand cursor-pointer"
                    />
                    <button
                      type="button"
                      disabled={isRendering}
                      onClick={() => nudgeStart(0.5)}
                      className="rounded-lg bg-surface border border-border px-2 py-1 text-xs font-mono text-muted hover:text-fg hover:bg-surface-3 transition"
                    >
                      +0.5s
                    </button>
                  </div>
                </div>

                {/* End Trim Control */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted font-medium">End Boundary:</span>
                    <span className="font-mono text-fg font-semibold">{fmtSeconds(endS)}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      disabled={isRendering}
                      onClick={() => nudgeEnd(-0.5)}
                      className="rounded-lg bg-surface border border-border px-2 py-1 text-xs font-mono text-muted hover:text-fg hover:bg-surface-3 transition"
                    >
                      -0.5s
                    </button>
                    <input
                      type="range"
                      min={startS + 3}
                      max={maxSourceDuration}
                      step={0.1}
                      value={endS}
                      disabled={isRendering}
                      onChange={(e) => setEndS(parseFloat(e.target.value))}
                      className="flex-1 accent-cyan-brand cursor-pointer"
                    />
                    <button
                      type="button"
                      disabled={isRendering}
                      onClick={() => nudgeEnd(0.5)}
                      className="rounded-lg bg-surface border border-border px-2 py-1 text-xs font-mono text-muted hover:text-fg hover:bg-surface-3 transition"
                    >
                      +0.5s
                    </button>
                  </div>
                </div>
              </div>

              {/* Title & Opening Hook Card Editor */}
              <div className="rounded-2xl border border-border/80 bg-surface-2/40 p-4 space-y-3">
                <div className="space-y-1">
                  <label htmlFor="clip-title-input" className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5">
                    <span>Short Title</span>
                  </label>
                  <input
                    id="clip-title-input"
                    type="text"
                    value={title}
                    disabled={isRendering}
                    onChange={(e) => setTitle(e.target.value)}
                    className="w-full rounded-xl bg-surface border border-border px-3 py-2 text-xs font-medium text-fg focus:outline-none focus:border-violet-brand"
                    placeholder="Engaging YouTube/TikTok Title"
                  />
                </div>

                <div className="space-y-1">
                  <label htmlFor="clip-hook-input" className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5">
                    <Sparkles className="size-3.5 text-violet-brand" />
                    <span>Opening Hook Card (First 3s)</span>
                  </label>
                  <input
                    id="clip-hook-input"
                    type="text"
                    value={hookText}
                    disabled={isRendering}
                    onChange={(e) => setHookText(e.target.value)}
                    className="w-full rounded-xl bg-surface border border-border px-3 py-2 text-xs font-medium text-fg focus:outline-none focus:border-violet-brand"
                    placeholder="Eye-catching question or bold statement"
                  />
                </div>
              </div>

              {/* Subtitles & Polish Style Bar */}
              <div className="rounded-2xl border border-border/80 bg-surface-2/40 p-4 space-y-3">
                {/* Kinetic Subtitles */}
                <div>
                  <span className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5 mb-2">
                    <Sparkles className="size-3 text-violet-brand" />
                    <span>Kinetic Subtitles Style</span>
                  </span>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
                    {[
                      { id: "hormozi", label: "⚡ Hormozi" },
                      { id: "mrbeast", label: "🟢 MrBeast" },
                      { id: "neon", label: "🟣 Cyber" },
                      { id: "clean", label: "⚪ Clean" },
                    ].map((preset) => (
                      <button
                        key={preset.id}
                        type="button"
                        disabled={isRendering}
                        onClick={() => setSubtitleStyle(preset.id)}
                        className={clsx(
                          "rounded-xl px-2 py-1.5 text-xs font-medium transition text-center",
                          subtitleStyle === preset.id
                            ? "bg-violet-brand text-white shadow-md font-semibold"
                            : "bg-surface text-muted hover:text-fg hover:bg-surface-3"
                        )}
                      >
                        {preset.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Auto-Zoom & Mood Audio */}
                <div className="pt-2 border-t border-border/60 grid grid-cols-2 gap-3">
                  <div>
                    <span className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1 mb-1.5">
                      <ZoomIn className="size-3 text-cyan-brand" />
                      <span>Auto-Zoom</span>
                    </span>
                    <button
                      type="button"
                      disabled={isRendering}
                      onClick={() => setAutoZoom(!autoZoom)}
                      className={clsx(
                        "w-full rounded-xl px-3 py-1.5 text-xs font-medium transition flex items-center justify-center gap-2",
                        autoZoom
                          ? "bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 font-semibold"
                          : "bg-surface text-muted border border-border hover:text-fg"
                      )}
                    >
                      <span className={clsx("size-1.5 rounded-full", autoZoom ? "bg-cyan-400 animate-pulse" : "bg-muted")} />
                      {autoZoom ? "Punch-in ON" : "Static 1.0x"}
                    </button>
                  </div>

                  <div>
                    <span className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1 mb-1.5">
                      <Music className="size-3 text-violet-brand" />
                      <span>Audio Bed</span>
                    </span>
                    <select
                      disabled={isRendering}
                      value={musicMood || "none"}
                      onChange={(e) => setMusicMood(e.target.value === "none" ? null : e.target.value)}
                      className="w-full rounded-xl bg-surface border border-border px-3 py-1.5 text-xs font-medium text-fg focus:outline-none focus:border-violet-brand cursor-pointer"
                    >
                      <option value="none">Speech Only</option>
                      <option value="chill">☕ Chill Lo-fi</option>
                      <option value="energetic">⚡ Upbeat Beat</option>
                      <option value="suspense">🎬 Suspense Drama</option>
                    </select>
                  </div>
                </div>
              </div>

              {/* Error / Success Feedback */}
              {errorMsg && (
                <div className="flex items-center gap-2 rounded-xl bg-rose-500/10 border border-rose-500/30 px-3 py-2 text-xs text-rose-300">
                  <AlertCircle className="size-4 shrink-0" />
                  <span>{errorMsg}</span>
                </div>
              )}
              {successNotice && (
                <div className="flex items-center gap-2 rounded-xl bg-emerald-500/10 border border-emerald-500/30 px-3 py-2 text-xs text-emerald-300">
                  <Check className="size-4 shrink-0" />
                  <span>Clip successfully trimmed and re-rendered!</span>
                </div>
              )}
            </div>
          </div>

          {/* Modal Footer */}
          <div className="border-t border-border/70 px-5 py-3.5 bg-surface-2/40 flex items-center justify-between">
            <button
              type="button"
              disabled={isRendering}
              onClick={handleReset}
              className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-surface px-3 py-1.5 text-xs font-medium text-muted hover:text-fg hover:bg-surface-3 transition"
            >
              <RotateCcw className="size-3.5" />
              <span>Reset</span>
            </button>

            <div className="flex items-center gap-2.5">
              <button
                type="button"
                disabled={isRendering}
                onClick={onClose}
                className="rounded-xl px-4 py-1.5 text-xs font-medium text-muted hover:text-fg transition"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={isRendering}
                onClick={handleSaveAndRerender}
                className="inline-flex items-center gap-2 rounded-xl bg-violet-brand px-5 py-1.5 text-xs font-semibold text-white shadow-lg shadow-violet-brand/30 hover:bg-violet-600 transition disabled:opacity-50"
              >
                {isRendering ? (
                  <>
                    <RefreshCw className="size-3.5 animate-spin" />
                    <span>Re-rendering...</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="size-3.5" />
                    <span>Apply & Re-render (⚡)</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
