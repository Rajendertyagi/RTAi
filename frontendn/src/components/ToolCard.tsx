import { useLayoutEffect, useMemo, useRef } from "react";
import type { EnrichedPartState } from "@assistant-ui/react";
import { useChat } from "../state/ChatContext";
import type { ToolCall, ToolContent, ToolLocation } from "../types/protocol";
import { useColorScheme } from "../hooks/useColorScheme";
import { useStreamingTextThrottle } from "../hooks/useStreamingTextThrottle";
import { CodeBlock } from "./CodeBlock";
import { DiffPreview } from "./DiffPreview";
import { ToolIcon } from "./Icons";

type ToolPart = Extract<EnrichedPartState, { type: "tool-call" }>;

const TOOL_LABEL: Record<string, string> = {
  pending: "Queued",
  running: "Running",
  success: "Done",
  error: "Failed",
  cancelled: "Cancelled",
  aborted: "Aborted",
  timeout: "Timed out",
};

// Collapse OpenCode's many tool spellings to a small display set.
const TOOL_ALIASES: Record<string, string> = {
  edit: "edit",
  multiedit: "edit",
  str_replace: "edit",
  apply_patch: "edit",
  bash: "bash",
  shell: "bash",
  cmd: "bash",
  terminal: "bash",
  shell_command: "bash",
};

function normalizeToolName(title: string): string {
  return TOOL_ALIASES[title] ?? title;
}

function relativePath(path: string, cwd: string): string {
  if (!cwd) return path;
  const base = cwd.replace(/[\\/]+$/, "");
  if (path.startsWith(base)) {
    const rel = path.slice(base.length).replace(/^[\\/]/, "");
    return rel || path;
  }
  return path;
}

function commandFromRawInput(rawInput: unknown): string | null {
  if (typeof rawInput === "string") return rawInput;
  if (rawInput && typeof rawInput === "object") {
    const obj = rawInput as Record<string, unknown>;
    if (typeof obj.command === "string") return obj.command;
    if (typeof obj.content === "string") return obj.content;
  }
  return null;
}

function textFromContent(content?: ToolContent[]): string {
  if (!content) return "";
  return content
    .filter((c): c is { type: "content"; text?: string } => c.type === "content")
    .map((c) => c.text ?? "")
    .join("");
}

function diffFromContent(
  content?: ToolContent[],
): { path: string; oldText?: string; newText: string } | null {
  if (!content) return null;
  const block = content.find((c) => c.type === "diff");
  if (!block || block.type !== "diff") return null;
  return { path: block.path, oldText: block.oldText, newText: block.newText };
}

/**
 * Append-only streaming text: while a tool runs, output updates append only
 * the new characters to the existing text node instead of re-rendering the
 * whole block. Same technique OpenChamber uses for live tool output.
 */
function StreamingText({ text }: { text: string }) {
  const preRef = useRef<HTMLPreElement>(null);
  const prevRef = useRef("");

  useLayoutEffect(() => {
    const el = preRef.current;
    if (!el) return;
    const first = el.firstChild;
    const node = first instanceof Text ? first : document.createTextNode("");
    if (node !== first) el.replaceChildren(node);
    const prev = prevRef.current;
    if (text.startsWith(prev)) {
      node.appendData(text.slice(prev.length));
    } else {
      node.data = text;
    }
    prevRef.current = text;
  }, [text]);

  return <pre ref={preRef} className="tool-output-streaming" />;
}

/**
 * Smart tool card. The RTAI ToolCall rides along as the part's `artifact`, so
 * the card renders the authoritative status/locations/content from it instead
 * of re-deriving anything from the assistant-ui part.
 */
export function ToolCard({ part }: { part: ToolPart }) {
  const { state } = useChat();
  const scheme = useColorScheme();
  const cwd = state.cwd;

  const tool = part.artifact as ToolCall | undefined;
  const status =
    tool?.status ??
    (part.isError ? "error" : part.result !== undefined ? "success" : "running");
  const isRunning = status === "running" || status === "pending";
  const name = normalizeToolName(tool?.title ?? part.toolName);
  const kind = tool?.kind;
  const diff = diffFromContent(tool?.content);
  const outputText = textFromContent(tool?.content);
  const command = commandFromRawInput(tool?.rawInput);
  const throttledOutput = useStreamingTextThrottle({
    text: outputText,
    isStreaming: isRunning,
    identityKey: tool?.id ?? part.toolCallId,
    allowTextReplacement: true,
  });

  const rawPreview = useMemo(() => {
    if (command || diff || outputText || tool?.rawInput === undefined) return null;
    try {
      return JSON.stringify(tool?.rawInput, null, 2);
    } catch {
      return String(tool?.rawInput);
    }
  }, [command, diff, outputText, tool?.rawInput]);

  return (
    <div className={`tool-card ${status}`}>
      <div className="tool-card-header">
        <ToolIcon kind={kind} />
        <span className="tool-card-name">{name}</span>
        <span className="tool-card-status">{TOOL_LABEL[status] ?? status}</span>
      </div>

      {tool?.locations && tool.locations.length > 0 && (
        <div className="tool-card-locations">
          {tool.locations.map((loc: ToolLocation, index: number) => (
            <span key={index} className="tool-location" title={loc.path}>
              {relativePath(loc.path, cwd)}
              {loc.line != null ? `:${loc.line}` : ""}
            </span>
          ))}
        </div>
      )}

      {command && (
        <div className="tool-card-command">
          <CodeBlock code={command} language="bash" complete={true} scheme={scheme} />
        </div>
      )}

      {diff && (
        <DiffPreview
          oldText={diff.oldText}
          newText={diff.newText}
          path={relativePath(diff.path, cwd)}
        />
      )}

      {outputText &&
        (isRunning ? (
          <StreamingText text={throttledOutput} />
        ) : (
          <div className="tool-card-output">
            <CodeBlock code={throttledOutput} language={null} complete={!isRunning} scheme={scheme} />
          </div>
        ))}

      {rawPreview && <pre className="tool-card-raw">{rawPreview}</pre>}
    </div>
  );
}