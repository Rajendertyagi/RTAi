import {
  Fragment,
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  LANGUAGE_LABELS,
  loadHighlighter,
  normalizeLanguage,
  shikiThemeFor,
  type ColorScheme,
  type Highlighter,
} from "../lib/shikiHighlighter";

// FontStyle bit flags from @shikijs/vscode-textmate:
// Italic = 1, Bold = 2, Underline = 4, Strikethrough = 8.
const ITALIC = 1;
const BOLD = 2;
const UNDERLINE = 4;
const STRIKETHROUGH = 8;

/** Minimal structural view of a Shiki ThemedToken that we actually render. */
interface Token {
  content: string;
  color?: string;
  bgColor?: string;
  fontStyle?: number;
}

interface Highlighted {
  lines: Token[][];
  fg?: string;
  bg?: string;
}

const COPIED_RESET_MS = 1600;

function tokenStyle(token: Token): CSSProperties | undefined {
  const style: CSSProperties = {};
  if (token.color) style.color = token.color;
  if (token.bgColor) style.backgroundColor = token.bgColor;

  const font = token.fontStyle ?? 0;
  if (font & ITALIC) style.fontStyle = "italic";
  if (font & BOLD) style.fontWeight = 600;

  const decorations: string[] = [];
  if (font & UNDERLINE) decorations.push("underline");
  if (font & STRIKETHROUGH) decorations.push("line-through");
  if (decorations.length > 0) style.textDecoration = decorations.join(" ");

  return Object.keys(style).length > 0 ? style : undefined;
}

export interface CodeBlockProps {
  /** Original code text - this is what gets copied, never the markup. */
  code: string;
  /** Raw fence language. Untrusted; normalised internally. */
  language?: string | null;
  /** Authoritative completion state of the owning message. */
  complete: boolean;
  scheme: ColorScheme;
}

export function CodeBlock({ code, language, complete, scheme }: CodeBlockProps) {
  const lang = normalizeLanguage(language);
  const [highlighted, setHighlighted] = useState<Highlighted | null>(null);
  const [copied, setCopied] = useState(false);
  const resetTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    // While the message is still streaming we render plain text only: calling
    // Shiki on every delta would tokenise the same block hundreds of times.
    if (!complete) {
      setHighlighted(null);
      return;
    }

    let cancelled = false;
    loadHighlighter()
      .then((highlighter: Highlighter) => {
        if (cancelled) return;
        const result = highlighter.codeToTokens(code, {
          lang,
          theme: shikiThemeFor(scheme),
        });
        setHighlighted({
          lines: result.tokens as unknown as Token[][],
          fg: result.fg,
          bg: result.bg,
        });
      })
      .catch(() => {
        // Highlighting is an enhancement. On failure keep the plain block.
        if (!cancelled) setHighlighted(null);
      });

    return () => {
      cancelled = true;
    };
  }, [code, lang, complete, scheme]);

  useEffect(() => () => window.clearTimeout(resetTimer.current), []);

  const copy = useCallback(async () => {
    try {
      // Clipboard API is unavailable on insecure origins and can reject on
      // permission denial; neither may break the message.
      if (!navigator.clipboard?.writeText) return;
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.clearTimeout(resetTimer.current);
      resetTimer.current = window.setTimeout(() => setCopied(false), COPIED_RESET_MS);
    } catch {
      setCopied(false);
    }
  }, [code]);

  const preStyle: CSSProperties = {};
  if (highlighted?.fg) preStyle.color = highlighted.fg;
  if (highlighted?.bg) preStyle.backgroundColor = highlighted.bg;

  return (
    <div className="code-block-wrapper">
      <div className="code-header">
        <span className="code-lang">{LANGUAGE_LABELS[lang] ?? lang}</span>
        <button
          className="code-copy-btn"
          type="button"
          onClick={copy}
          aria-label="Copy code"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {/* tabIndex keeps long/wide code reachable by keyboard. */}
      <pre tabIndex={0} style={preStyle}>
        <code>
          {highlighted
            ? highlighted.lines.map((line, lineIndex) => (
                <Fragment key={lineIndex}>
                  {line.map((token, tokenIndex) => (
                    <span key={tokenIndex} style={tokenStyle(token)}>
                      {token.content}
                    </span>
                  ))}
                  {lineIndex < highlighted.lines.length - 1 ? "\n" : null}
                </Fragment>
              ))
            : code}
        </code>
      </pre>
      {/* Announced without moving focus. */}
      <span className="sr-only" role="status" aria-live="polite">
        {copied ? "Code copied to clipboard" : ""}
      </span>
    </div>
  );
}
