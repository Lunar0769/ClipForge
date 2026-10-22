import { LoaderCircle, TriangleAlert } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useId, useRef } from "react";

interface Props {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  pending?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Accessible confirmation for destructive actions (Esc / backdrop cancel, focus starts on Cancel). */
export function ConfirmDialog({
  open, title, message, confirmLabel = "Delete", pending = false, error, onConfirm, onCancel,
}: Props) {
  const titleId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !pending && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, pending, onCancel]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[60] grid place-items-center bg-black/70 p-4 backdrop-blur-sm"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={(e) => { e.stopPropagation(); if (!pending) onCancel(); }}
        >
          <motion.div
            role="alertdialog" aria-modal="true" aria-labelledby={titleId}
            initial={{ y: 16, scale: 0.97 }} animate={{ y: 0, scale: 1 }} exit={{ y: 16, scale: 0.97 }}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-sm rounded-2xl border border-border bg-bg p-5 shadow-2xl"
          >
            <div className="flex gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-red-500/15 text-red-400">
                <TriangleAlert className="size-4" aria-hidden="true" />
              </span>
              <div>
                <h2 id={titleId} className="font-display text-lg font-semibold">{title}</h2>
                <p className="mt-1 text-sm text-muted">{message}</p>
                {error && <p role="alert" className="mt-2 text-sm text-red-400">{error}</p>}
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button ref={cancelRef} type="button" onClick={onCancel} disabled={pending}
                className="rounded-xl px-4 py-2 text-sm text-muted transition hover:bg-surface-2 hover:text-fg">
                Cancel
              </button>
              <button type="button" onClick={onConfirm} disabled={pending}
                className="inline-flex items-center gap-2 rounded-xl bg-red-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-600 disabled:opacity-60">
                {pending && <LoaderCircle className="size-4 animate-spin" />}
                {confirmLabel}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
