import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type Theme = "light" | "dark";

/** Keep in sync with the pre-paint script in index.html. */
const STORAGE_KEY = "bb-theme";

function systemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** The user's explicit choice, or null while they are still following the OS. */
function readStored(): Theme | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

interface ThemeContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // index.html has already written data-theme; read it back rather than recomputing, so the
  // provider and the DOM can never disagree on the first render.
  const [theme, setThemeState] = useState<Theme>(
    () =>
      (document.documentElement.getAttribute("data-theme") as Theme | null) ??
      readStored() ??
      systemTheme(),
  );

  // Reflect the theme onto <html>. Deliberately does NOT write localStorage: doing so here
  // would stamp an explicit choice on the first visit and detach the app from the OS setting
  // before the user ever touched the toggle. Only setTheme persists.
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // Follow the OS until the user makes an explicit choice. The stored-value check happens
  // inside the handler, not at subscribe time, so a choice made later takes effect without
  // needing to resubscribe.
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => {
      if (readStored()) return;
      setThemeState(e.matches ? "dark" : "light");
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Private browsing / storage disabled -- the theme still applies for this session.
    }
  }, []);

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}
