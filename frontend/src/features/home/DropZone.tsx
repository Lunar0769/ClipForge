import clsx from "clsx";
import { Upload } from "lucide-react";
import { motion } from "motion/react";
import { useRef, useState, type DragEvent } from "react";
import { api } from "../../lib/api";
import { fileExtension } from "../../lib/format";
import type { Project } from "../../lib/types";
import { UPLOAD_EXTENSIONS } from "../../lib/url";

export function DropZone({ onUploaded, className }: { onUploaded: (p: Project) => void; className?: string }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleFile = async (file: File) => {
    if (!UPLOAD_EXTENSIONS.includes(fileExtension(file.name))) {
      setError(`Unsupported file type. Use ${UPLOAD_EXTENSIONS.join(", ")}.`);
      return;
    }
    setError(null);
    setProgress(0);
    try {
      onUploaded(await api.upload(file, setProgress));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
      setProgress(null);
    }
  };

  const onDrag = (e: DragEvent, over: boolean) => {
    e.preventDefault();
    setDragging(over);
  };

  return (
    <div className={className}>
      <motion.div animate={{ scale: dragging ? 1.02 : 1 }} transition={{ type: "spring", stiffness: 300, damping: 22 }}>
        <button
          type="button"
          disabled={progress !== null}
          onClick={() => inputRef.current?.click()}
          onDragEnter={(e) => onDrag(e, true)}
          onDragOver={(e) => onDrag(e, true)}
          onDragLeave={(e) => onDrag(e, false)}
          onDrop={(e) => {
            onDrag(e, false);
            const file = e.dataTransfer.files[0];
            if (file) void handleFile(file);
          }}
          className={clsx(
            "relative flex w-full flex-col items-center gap-3 overflow-hidden rounded-2xl border border-dashed px-6 py-10 transition",
            dragging
              ? "border-cyan-brand bg-cyan-brand/10 shadow-[0_0_60px_-20px_var(--color-cyan-brand)]"
              : "border-border bg-surface hover:border-violet-brand/60 hover:bg-surface-2",
          )}
        >
          <span className="grid size-12 place-items-center rounded-xl bg-surface-2">
            <Upload className="size-5" aria-hidden="true" />
          </span>
          <span className="text-sm font-medium">
            {progress === null ? "Drop a video file or click to browse" : `Uploading… ${Math.round(progress * 100)}%`}
          </span>
          <span className="text-xs text-muted">MP4, MKV, MOV, WebM · any length</span>
          {progress !== null && (
            <motion.span
              className="absolute inset-x-0 bottom-0 h-1 origin-left bg-gradient-to-r from-violet-brand to-cyan-brand"
              animate={{ scaleX: progress }}
            />
          )}
        </button>
      </motion.div>
      <input
        ref={inputRef}
        type="file"
        accept={`${UPLOAD_EXTENSIONS.join(",")},video/*`}
        className="sr-only"
        data-testid="file-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void handleFile(file);
          e.target.value = "";
        }}
      />
      {error && <p role="alert" className="mt-3 text-sm text-red-400">{error}</p>}
    </div>
  );
}
