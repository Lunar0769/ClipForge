import { Link } from "react-router";
import { PageTransition } from "./PageTransition";

export function NotFound({ message = "This page doesn't exist." }: { message?: string }) {
  return (
    <PageTransition>
      <div className="mx-auto flex max-w-md flex-col items-center px-4 py-32 text-center">
        <p className="font-display text-7xl font-semibold text-gradient">404</p>
        <p className="mt-4 text-muted">{message}</p>
        <Link to="/" className="mt-8 rounded-full bg-fg px-5 py-2.5 text-sm font-semibold text-bg">
          Back to ClipForge
        </Link>
      </div>
    </PageTransition>
  );
}
