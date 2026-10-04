import clsx from "clsx";

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={clsx(
        "animate-shimmer rounded-xl bg-[length:200%_100%]",
        "bg-[linear-gradient(90deg,var(--surface)_25%,var(--surface-2)_50%,var(--surface)_75%)]",
        className,
      )}
    />
  );
}
