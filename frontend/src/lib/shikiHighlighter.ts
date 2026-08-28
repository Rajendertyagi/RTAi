/**
 * Lazy Shiki singleton.
 *
 * Shiki is pulled in with a dynamic `import()` so Vite emits it as its own
 * chunk, fetched only when a *completed* message actually contains a fenced
 * code block. The chat bundle itself holds no Shiki code.
 *
 * One highlighter is created and reused for the whole app: Shiki's own docs
 * warn instances are expensive and must be long-lived singletons, never
 * created per call site.
 *
 * Verified against Shiki 4.4.3 (https://shiki.style/guide/install):
 *   - `createHighlighter({ themes, langs })` is the singleton factory
 *   - `highlighter.codeToTokens(code, { lang, theme })` returns token lines
 *   - every language/theme id below is a bundled id per shiki.style/languages
 *     and shiki.style/themes
 */

// Type-only reference. Erased at compile time, so it drags in no runtime code
// and does not defeat the dynamic import below.
type ShikiModule = typeof import("shiki");

export type Highlighter = Awaited<ReturnType<ShikiModule["createHighlighter"]>>;

// Also type-only: `codeToTokens` is typed against BundledLanguage, so our
// normalised ids have to carry that type or the call will not compile.
import type { BundledLanguage } from "shiki";

/**
 * Deliberately small, chat-oriented language set. Loading every grammar would
 * mean hundreds of chunks; these cover the languages that actually show up in
 * coding-chat output.
 */
export const SHIKI_LANGUAGES = [
  "text",
  "shellscript",
  "powershell",
  "python",
  "javascript",
  "typescript",
  "jsx",
  "tsx",
  "json",
  "html",
  "css",
  "markdown",
] as const;

export const SHIKI_THEMES = ["github-light", "github-dark"] as const;

export type ShikiTheme = (typeof SHIKI_THEMES)[number];
export type ColorScheme = "light" | "dark";

export function shikiThemeFor(scheme: ColorScheme): ShikiTheme {
  return scheme === "dark" ? "github-dark" : "github-light";
}

/** Human-readable labels for the language header. */
export const LANGUAGE_LABELS: Record<string, string> = {
  text: "Text",
  shellscript: "Shell",
  powershell: "PowerShell",
  python: "Python",
  javascript: "JavaScript",
  typescript: "TypeScript",
  jsx: "JSX",
  tsx: "TSX",
  json: "JSON",
  html: "HTML",
  css: "CSS",
  markdown: "Markdown",
};

/**
 * Aliases models commonly emit, mapped onto ids we actually load. Anything
 * unrecognised falls back to plain text: we never auto-detect a language and
 * never let an untrusted string reach Shiki as a grammar id.
 */
const LANGUAGE_ALIASES: Record<string, string> = {
  txt: "text",
  plain: "text",
  plaintext: "text",
  bash: "shellscript",
  sh: "shellscript",
  shell: "shellscript",
  zsh: "shellscript",
  console: "shellscript",
  ps: "powershell",
  ps1: "powershell",
  pwsh: "powershell",
  py: "python",
  js: "javascript",
  cjs: "javascript",
  mjs: "javascript",
  node: "javascript",
  ts: "typescript",
  cts: "typescript",
  mts: "typescript",
  md: "markdown",
  htm: "html",
  jsonc: "json",
};

const LOADED = new Set<string>(SHIKI_LANGUAGES);

/**
 * Normalise an untrusted fence language to a loaded Shiki id, else "text".
 * Only characters from a conservative set are considered, and the result is
 * never used as a CSS class or HTML fragment.
 */
export function normalizeLanguage(raw: string | null | undefined): BundledLanguage {
  if (typeof raw !== "string") return "text";
  const key = raw.trim().toLowerCase();
  if (LOADED.has(key)) return key as BundledLanguage;
  const mapped = LANGUAGE_ALIASES[key];
  return (mapped && LOADED.has(mapped) ? mapped : "text") as BundledLanguage;
}

let pending: Promise<Highlighter> | null = null;

/**
 * Resolve the shared highlighter, creating it on first use.
 * A rejection clears the cache so a later block can retry.
 */
export function loadHighlighter(): Promise<Highlighter> {
  if (!pending) {
    pending = import("shiki")
      .then(({ createHighlighter }) =>
        createHighlighter({
          themes: [...SHIKI_THEMES],
          langs: [...SHIKI_LANGUAGES],
        }),
      )
      .catch((error: unknown) => {
        pending = null;
        throw error;
      });
  }
  return pending;
}
