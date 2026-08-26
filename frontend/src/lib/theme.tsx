import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type Theme = "light" | "dark";

/** Keep in sync with the pre-paint script in index.html. */
const STORAGE_KEY = "bb-theme";

function systemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

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
  toggleTheme: () => void;
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

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // Private browsing / storage disabled -- the theme still applies for this session.
    }
  }, [theme]);

  // Follow the OS only while the user has not made an explicit choice.
  useEffect(() => {
    if (readStored()) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => setThemeState(e.matches ? "dark" : "light");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const setTheme = useCallback((next: Theme) => setThemeState(next), []);
  const toggleTheme = useCallback(
    () => setThemeState((t) => (t === "dark" ? "light" : "dark")),
    [],
  );

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}
