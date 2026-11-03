import { useCallback, useState } from "react";

export function useTheme() {
  const [theme, setTheme] = useState<"light" | "dark">(() => (document.documentElement.dataset.theme === "dark" ? "dark" : "light"));
  const toggle = useCallback(() => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("vand-theme", next); } catch { /* storage may be unavailable; preference simply won't persist */ }
    setTheme(next);
  }, [theme]);
  return { theme, toggle };
}
