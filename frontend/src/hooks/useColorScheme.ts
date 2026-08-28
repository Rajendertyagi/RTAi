import { useEffect, useState } from "react";
import type { ColorScheme } from "../lib/shikiHighlighter";

const STORAGE_KEY = "theme";

function resolveScheme(): ColorScheme {
  if (typeof window === "undefined") return "light";
  // ChatContext writes "dark"/"light" here when the toggle is used.
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "dark" || stored === "light") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/**
 * Current light/dark scheme, kept in sync with however the theme was changed.
 *
 * Three signals are watched because the app can be switched three ways:
 *   - the header toggle flips a `dark` class on <html> (same tab, so no
 *     `storage` event fires — hence the MutationObserver)
 *   - the OS preference can change underneath us (matchMedia)
 *   - another tab can change it (`storage` event)
 */
export function useColorScheme(): ColorScheme {
  const [scheme, setScheme] = useState<ColorScheme>(resolveScheme);

  useEffect(() => {
    const update = () => setScheme(resolveScheme());

    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", update);
    window.addEventListener("storage", update);

    return () => {
      observer.disconnect();
      media.removeEventListener("change", update);
      window.removeEventListener("storage", update);
    };
  }, []);

  return scheme;
}
