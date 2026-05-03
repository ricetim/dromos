import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { AppTheme, THEMES } from "../config";

interface ThemeCtx {
  theme: AppTheme;
  setTheme: (t: AppTheme) => void;
  themes: typeof THEMES;
}

const Ctx = createContext<ThemeCtx | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<AppTheme>(
    () => (localStorage.getItem("theme") as AppTheme | null) ?? "default"
  );

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "default") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", theme);
    }
    localStorage.setItem("theme", theme);
  }, [theme]);

  function setTheme(t: AppTheme) {
    setThemeState(t);
  }

  return <Ctx.Provider value={{ theme, setTheme, themes: THEMES }}>{children}</Ctx.Provider>;
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
