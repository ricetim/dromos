import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { AppTheme, THEMES, DEFAULT_THEME, THEME_STORAGE_KEY } from "../config";

interface ThemeCtx {
  theme: AppTheme;
  setTheme: (t: AppTheme) => void;
  themes: typeof THEMES;
}

const Ctx = createContext<ThemeCtx | null>(null);

/** The user's explicit choice, if any and still valid; otherwise the default.
 *  Storage access is guarded, since it throws in some private/locked-down modes. */
function initialTheme(): AppTheme {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    if (saved && THEMES.some((t) => t.key === saved)) return saved as AppTheme;
  } catch {
    /* storage unavailable: fall through to the default */
  }
  return DEFAULT_THEME;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<AppTheme>(initialTheme);

  // Apply to <html>. index.html already did this before first paint; this
  // keeps it in sync with later changes. Only the "default" theme has no
  // attribute, since its styles are the unscoped base CSS.
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "default") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
  }, [theme]);

  // Persist only explicit choices. Writing on every load (the old behaviour)
  // turned the fallback into a "saved preference" nobody had actually made.
  function setTheme(t: AppTheme) {
    setThemeState(t);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, t);
    } catch {
      /* storage unavailable: the choice lasts for this session only */
    }
  }

  return <Ctx.Provider value={{ theme, setTheme, themes: THEMES }}>{children}</Ctx.Provider>;
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
