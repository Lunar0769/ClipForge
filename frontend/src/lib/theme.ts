export type Theme = "dark" | "light";
const KEY = "clipforge-theme";

export function getStoredTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* storage unavailable (private mode) — theme still applies for this visit */
  }
}

export function applyStoredTheme(): void {
  applyTheme(getStoredTheme());
}
