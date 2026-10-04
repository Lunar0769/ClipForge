import { LoaderCircle, RotateCcw, TriangleAlert } from "lucide-react";
import { motion } from "motion/react";

interface Props {
  title: string;
  message: string | null;
  hint: string | null;
  onRetry: () => void;
  pending: boolean;
}

export function ErrorPanel({ title, message, hint, onRetry, pending }: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      className="mt-8 flex flex-col gap-4 rounded-2xl border border-red-500/30 bg-red-500/5 p-5 sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="flex gap-3">
        <TriangleAlert className="mt-0.5 size-5 shrink-0 text-red-400" aria-hidden="true" />
        <div>
          <p className="font-medium">{title}</p>
          {message && <p className="mt-1 text-sm text-muted">{message}</p>}
          {hint && <p className="mt-2 text-sm">{hint}</p>}
        </div>
      </div>
      <button
        type="button"
        onClick={onRetry}
        disabled={pending}
        className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-fg px-4 py-2.5 text-sm font-semibold text-bg disabled:opacity-60"
      >
        {pending ? <LoaderCircle className="size-4 animate-spin" /> : <RotateCcw className="size-4" />}
        Retry
      </button>
    </motion.div>
  );
}
