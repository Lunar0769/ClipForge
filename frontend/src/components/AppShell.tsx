import { Moon, Sun } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { applyTheme, getStoredTheme, type Theme } from "../lib/theme";
import { useSmoothScroll } from "../lib/useSmoothScroll";
import { Grain } from "./Grain";
import { Logo } from "./Logo";

export function AppShell({ children }: { children: ReactNode }) {
  useSmoothScroll();
  const [theme, setTheme] = useState<Theme>(getStoredTheme);
  const next: Theme = theme === "dark" ? "light" : "dark";

  return (
    <div className="relative min-h-dvh overflow-x-clip">
      <Grain />
      <header className="sticky top-0 z-40 border-b border-border/60 bg-bg/70 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
          <Link to="/" className="flex items-center gap-2.5" aria-label="ClipForge home">
            <Logo className="size-8" />
            <span className="font-display text-lg font-semibold tracking-tight">
              Clip<span className="text-gradient">Forge</span>
            </span>
          </Link>
          <nav className="flex items-center gap-1">
            <Link to="/" className="rounded-full px-4 py-2 text-sm text-muted transition hover:bg-surface-2 hover:text-fg">
              New project
            </Link>
            <button
              type="button"
              aria-label={`Switch to ${next} theme`}
              onClick={() => {
                applyTheme(next);
                setTheme(next);
              }}
              className="grid size-9 place-items-center rounded-full text-muted transition hover:bg-surface-2 hover:text-fg"
            >
              {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </button>
          </nav>
        </div>
      </header>
      <main>{children}</main>
    </div>
  );
}
