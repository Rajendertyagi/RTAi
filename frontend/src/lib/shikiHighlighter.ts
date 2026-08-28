/**
 * Lazy Shiki singleton, built from the **fine-grained bundle**.
 *
 * Everything Shiki-related is reached through dynamic `import()`, so Vite puts
 * it in its own chunks which are fetched only when a *completed* message
 * actually contains a fenced code block. The chat bundle holds no Shiki code.
 *
 * Why fine-grained rather than the `shiki` full bundle: importing `shiki`
 * pulls a dynamic-import map of every bundled grammar, and Vite emits a chunk
 * for each one. That produced 311 emitted assets (~10 MB) even though only a
 * handful could ever load. Importing grammars and themes explicitly means only
 * the ones we actually use are emitted.
 *
 * One highlighter is created and reused: Shiki's docs warn instances are
 * expensive and must be long-lived singletons.
 *
 * Verified against Shiki 4.4.3 published types:
 *   - `shiki/core` exports `createHighlighterCore`
 *   - `shiki/engine/oniguruma` exports `createOnigurumaEngine`
 *   - `highlighter.codeToTokens()` is synchronous and returns `TokensResult`
 *     (tokens / fg / bg)
 *   - `ThemedToken` carries content, color, bgColor, fontStyle
 *   - @shikijs/langs and @shikijs/themes expose `./<id>` subpaths
 */

// Type-only references. Erased at compile time, so they drag in no runtime
// code and do not defeat the dynamic imports below.
type CoreModule = typeof import("shiki/core");

export type Highlighter = Awaited<ReturnType<CoreModule["createHighlighterCore"]>>;

// `codeToTokens` is typed against the language union, so normalised ids have
// to carry this type or the call will not compile.
import type { BundledLanguage } from "shiki";

// Re-exported by shiki/core from @shikijs/types.
import type { LanguageInput, ThemeInput } from "shiki/core";

/**
 * Sentinel for "no highlighting". Shiki accepts "text" at runtime but it is
 * not part of the BundledLanguage union, so it cannot be preloaded. We treat
 * it as a bypass rather than a grammar.
 */
export const PLAIN_TEXT = "text" as const;

export type NormalizedLanguage = BundledLanguage | typeof PLAIN_TEXT;

/**
 * Deliberately small, chat-oriented language set. These cover the languages
 * that actually show up in coding-chat output; loading every grammar would mean
 * hundreds of chunks.
 */
export const SHIKI_LANGUAGES = [
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

export function normalizeLanguage(raw: string | null | undefined): NormalizedLanguage {
  if (typeof raw !== "string") return PLAIN_TEXT;
  const key = raw.trim().toLowerCase();
  if (LOADED.has(key)) return key as BundledLanguage;
  const mapped = LANGUAGE_ALIASES[key];
  return (mapped && LOADED.has(mapped) ? mapped : PLAIN_TEXT) as NormalizedLanguage;
}

/** Grammar modules, one dynamic import each. */
const LANGUAGE_LOADERS: Record<string, () => Promise<{ default: unknown }>> = {
  shellscript: () => import("@shikijs/langs/shellscript"),
  powershell: () => import("@shikijs/langs/powershell"),
  python: () => import("@shikijs/langs/python"),
  javascript: () => import("@shikijs/langs/javascript"),
  typescript: () => import("@shikijs/langs/typescript"),
  jsx: () => import("@shikijs/langs/jsx"),
  tsx: () => import("@shikijs/langs/tsx"),
  json: () => import("@shikijs/langs/json"),
  html: () => import("@shikijs/langs/html"),
  css: () => import("@shikijs/langs/css"),
  markdown: () => import("@shikijs/langs/markdown"),
};

/** Theme modules. Both load together so switching never reinitialises. */
const THEME_LOADERS: Record<ShikiTheme, () => Promise<{ default: unknown }>> = {
  "github-light": () => import("@shikijs/themes/github-light"),
  "github-dark": () => import("@shikijs/themes/github-dark"),
};

let pending: Promise<Highlighter> | null = null;

/**
 * Resolve the shared highlighter, creating it on first use.
 * A rejection clears the cache so a later block can retry.
 */
export function loadHighlighter(): Promise<Highlighter> {
  if (!pending) {
    pending = (async () => {
      const [{ createHighlighterCore }, { createOnigurumaEngine }] = await Promise.all([
        import("shiki/core"),
        import("shiki/engine/oniguruma"),
      ]);

      const [themes, langs] = await Promise.all([
        Promise.all(Object.values(THEME_LOADERS).map((load) => load())),
        Promise.all(Object.values(LANGUAGE_LOADERS).map((load) => load())),
      ]);

      return createHighlighterCore({
        // The grammar/theme modules are typed as unknown at the import
        // boundary; they satisfy LanguageInput / ThemeInput at runtime.
        themes: themes.map((module) => module.default) as unknown as ThemeInput[],
        langs: langs.map((module) => module.default) as unknown as LanguageInput[],
        engine: createOnigurumaEngine(import("shiki/wasm")),
      });
    })().catch((error: unknown) => {
      pending = null;
      throw error;
    });
  }
  return pending;
}
