/**
 * Single source of truth for light/dark theme.
 *
 * How theming actually works in this stylesheet: the design tokens are written
 * with the CSS `light-dark()` function, which resolves from the element's
 * `color-scheme`. `chat.css` sets `color-scheme` via `[data-theme="light"]` /
 * `[data-theme="dark"]` on the root element.
 *
 * So `data-theme` is the attribute that drives the application CSS. The
 * `dark` *class* has no CSS rule at all - it is kept in sync purely as a
 * legacy hook for anything that may still read it.
 *
 * Previously the toggle flipped only the class (no visual effect) while
 * useColorScheme independently read localStorage (driving Shiki), so the app
 * chrome and the code blocks could disagree. Everything now goes through this
 * module: the document, React state, and Shiki all read the same value.
 */

export type ThemePreference = "light" | "dark";

const STORAGE_KEY = "theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

let current: ThemePreference | null = null;
const listeners = new Set<() => void>();

function systemPreference(): ThemePreference {
  return window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

function storedPreference(): ThemePreference | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "dark" || value === "light" ? value : null;
  } catch {
    // Storage unavailable (private mode); fall back to the system.
    return null;
  }
}

/**
 * Prefer what the pre-paint script already applied, so React never disagrees
 * with what is on screen. Then an explicit stored choice, then the system.
 */
function compute(): ThemePreference {
  const applied = document.documentElement.dataset.theme;
  if (applied === "dark" || applied === "light") return applied;
  return storedPreference() ?? systemPreference();
}

export function getTheme(): ThemePreference {
  if (current === null) current = compute();
  return current;
}

function apply(theme: ThemePreference): void {
  const root = document.documentElement;
  // Drives color-scheme, and therefore every light-dark() token.
  root.dataset.theme = theme;
  // Legacy hook; kept in sync so nothing reads a stale value.
  root.classList.toggle("dark", theme === "dark");
}

function emit(): void {
  listeners.forEach((listener) => listener());
}

/** Sync the store with the pre-painted document. Call once before render. */
export function initTheme(): void {
  current = compute();
  apply(current);
  emit();
}

export function setTheme(theme: ThemePreference): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Persisting is best-effort; the in-memory theme still applies.
  }
  current = theme;
  apply(theme);
  emit();
}

export function toggleTheme(): void {
  setTheme(getTheme() === "dark" ? "light" : "dark");
}

/**
 * Subscribe for useSyncExternalStore. Same-tab changes are delivered through
 * our own listener set, so they apply immediately rather than waiting for a
 * `storage` event (which never fires in the originating tab).
 */
export function subscribeTheme(listener: () => void): () => void {
  listeners.add(listener);

  const media = window.matchMedia(DARK_QUERY);

  const onSystemChange = () => {
    // Only follow the system while the user has made no explicit choice.
    if (storedPreference() !== null) return;
    current = systemPreference();
    apply(current);
    emit();
  };

  const onStorage = (event: StorageEvent) => {
    if (event.key !== STORAGE_KEY) return;
    current = compute();
    apply(current);
    emit();
  };

  media.addEventListener("change", onSystemChange);
  window.addEventListener("storage", onStorage);

  return () => {
    listeners.delete(listener);
    media.removeEventListener("change", onSystemChange);
    window.removeEventListener("storage", onStorage);
  };
}
