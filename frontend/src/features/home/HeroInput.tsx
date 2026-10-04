import clsx from "clsx";
import { ArrowRight, Link2, LoaderCircle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState, type FormEvent } from "react";
import { MagneticButton } from "../../components/MagneticButton";
import { normalizeSourceUrl } from "../../lib/url";

interface Props {
  onSubmit: (url: string) => void;
  pending: boolean;
  serverError: string | null;
  className?: string;
}

export function HeroInput({ onSubmit, pending, serverError, className }: Props) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const shown = error ?? serverError;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const url = normalizeSourceUrl(value);
    if (!url) {
      setError("That doesn't look like a video link. Try https://youtube.com/watch?v=…");
      return;
    }
    setError(null);
    onSubmit(url);
  };

  return (
    <form onSubmit={submit} noValidate className={clsx("mx-auto w-full max-w-2xl", className)}>
      <div className="rounded-2xl bg-[linear-gradient(120deg,var(--color-violet-brand),var(--color-indigo-brand),var(--color-cyan-brand))] p-px shadow-[0_0_60px_-15px_var(--color-violet-brand)] transition-shadow focus-within:shadow-[0_0_90px_-10px_var(--color-violet-brand)]">
        <div className="flex items-center gap-2 rounded-[15px] bg-bg/90 p-2 pl-4 backdrop-blur-xl">
          <Link2 className="size-5 shrink-0 text-muted" aria-hidden="true" />
          <label htmlFor="source-url" className="sr-only">Video link</label>
          <input
            id="source-url"
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setError(null);
            }}
            placeholder="Paste a YouTube link…"
            autoComplete="off"
            inputMode="url"
            aria-invalid={!!shown}
            aria-describedby={shown ? "source-url-error" : undefined}
            className="min-w-0 flex-1 bg-transparent py-3 text-base outline-none placeholder:text-muted"
          />
          <MagneticButton
            type="submit"
            disabled={pending}
            aria-label={pending ? "Forging…" : "Forge clips"}
            className="inline-flex shrink-0 items-center gap-2 rounded-xl bg-fg px-5 py-3 text-sm font-semibold text-bg disabled:opacity-60"
          >
            {pending ? <LoaderCircle className="size-4 animate-spin" /> : <>Forge clips <ArrowRight className="size-4" /></>}
          </MagneticButton>
        </div>
      </div>
      <AnimatePresence>
        {shown && (
          <motion.p
            id="source-url-error"
            role="alert"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="mt-3 text-sm text-red-400"
          >
            {shown}
          </motion.p>
        )}
      </AnimatePresence>
    </form>
  );
}
