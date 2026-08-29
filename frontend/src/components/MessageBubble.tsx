import {
  Children,
  isValidElement,
  useMemo,
  type ComponentProps,
  type ReactNode,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useChat } from "../state/ChatContext";
import type { Message } from "../types/protocol";
import { CodeBlock } from "./CodeBlock";
import { ToolCallCard } from "./ToolCallCard";
import { PermissionCard } from "./PermissionCard";
import { ToolErrorBoundary } from "./ToolErrorBoundary";
import { useColorScheme } from "../hooks/useColorScheme";

/** Flatten rendered React children back to their plain text. */
function nodeToText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeToText).join("");
  if (isValidElement(node)) {
    return nodeToText((node.props as { children?: ReactNode }).children);
  }
  return "";
}

/** Pull the language out of react-markdown's `language-*` class. */
function languageFromClass(className: unknown): string | null {
  if (typeof className !== "string") return null;
  const match = /language-([A-Za-z0-9#+._-]+)/.exec(className);
  return match ? match[1] : null;
}

/**
 * Fenced code reaches us as <pre><code className="language-x">…</code></pre>.
 * Read the inner element's props instead of guessing from the text.
 */
function readFencedCode(children: ReactNode): { code: string; language: string | null } {
  const child = Children.toArray(children)[0];
  if (isValidElement(child)) {
    const props = child.props as { className?: unknown; children?: ReactNode };
    return {
      code: nodeToText(props.children).replace(/\n$/, ""),
      language: languageFromClass(props.className),
    };
  }
  return { code: nodeToText(children).replace(/\n$/, ""), language: null };
}

export function MessageBubble({ message }: { message: Message }) {
  const { state } = useChat();
  const scheme = useColorScheme();
  const cwd = state.cwd;

  // Authoritative completion state: set by the `done` event, not inferred
  // from whether a closing fence happens to have arrived yet.
  const complete = message.status === "complete";

  const components = useMemo(() => {
    // Taking over `pre` means the nested `code` renderer never runs for block
    // code, which leaves it responsible for inline code only.
    function Pre({ children }: ComponentProps<"pre">) {
      const { code, language } = readFencedCode(children);
      return (
        <CodeBlock code={code} language={language} complete={complete} scheme={scheme} />
      );
    }

    function InlineCode({ className, children }: ComponentProps<"code">) {
      return <code className={className}>{children}</code>;
    }

    return { pre: Pre, code: InlineCode };
  }, [complete, scheme]);

  const avatar = message.role === "user" ? "U" : message.role === "agent" ? "AI" : "⚠";

  return (
    <div className={`message ${message.role}`}>
      <div className="avatar">{avatar}</div>
      <div className="bubble">
        {message.role === "agent" ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
            {message.text}
          </ReactMarkdown>
        ) : (
          message.text
        )}

        {message.tools && message.tools.length > 0 && (
          <div className="tool-timeline">
            {message.tools.map((t) => (
              <ToolErrorBoundary key={t.id}>
                <ToolCallCard tool={t} cwd={cwd} />
              </ToolErrorBoundary>
            ))}
          </div>
        )}

        {message.permission && <PermissionCard permission={message.permission} cwd={cwd} />}
      </div>
    </div>
  );
}
