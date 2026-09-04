"use client";

import { useEffect, useState } from "react";
import {
  AuiIf,
  ErrorPrimitive,
  MessagePrimitive,
  ActionBarPrimitive,
  groupPartByType,
  useAui,
  useAuiState,
  type ThreadMessage,
} from "@assistant-ui/react";
import { Copy, Check, RotateCw, FileDown } from "lucide-react";

// Official Assistant UI Elements (registry-copied at immutable commit
// b6e7ab88b5e6e60866695d31a08adc3a80f449ff, pinned to @assistant-ui/react@0.15.17).
import {
  Reasoning,
  ReasoningRoot,
  ReasoningTrigger,
  ReasoningContent,
  ReasoningText,
} from "./assistant-ui/reasoning";
import {
  ToolGroupRoot,
  ToolGroupTrigger,
  ToolGroupContent,
} from "./assistant-ui/tool-group";
import { Image } from "./assistant-ui/image";
import { File } from "./assistant-ui/file";
import { MarkdownText } from "./assistant-ui/markdown-text";
import { ErrorState } from "./assistant-ui/elements/error-state";
import { StoppedRun } from "./assistant-ui/elements/stopped-run";
import { ThinkingIndicator } from "./assistant-ui/elements/thinking-indicator";
import { RtaiToolFallback } from "./assistant-ui/rtai-tool-fallback";
import { useRtaiCapabilities } from "@/hooks/useRtaiAssistantState";

// Assistant messages carry two extra, backend-stamped timing fields (see
// acp_state_projector._stamp_run_duration): started_at (float seconds) and
// duration_ms (int milliseconds). They are not part of the base ThreadMessage
// type, so we extend it locally for the footer timer.
type TimedMessage = ThreadMessage & {
  started_at?: number;
  duration_ms?: number;
};

const footerActionClass =
  "group flex h-7 w-7 items-center justify-center rounded-md bg-surface-elevated border border-border text-muted-foreground hover:text-foreground hover:bg-interactive-hover transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-interactive-focus-ring";

function MarkdownTextWrapper() {
  return <MarkdownText />;
}

function MessageError() {
  const aui = useAui();
  const isRunning = useAuiState((s) => s.thread.isRunning);
  return (
    <MessagePrimitive.Error>
      <ErrorState
        title="Something went wrong"
        detail={<ErrorPrimitive.Message />}
        retrying={isRunning}
        onRetry={() => aui.message.reload()}
      />
    </MessagePrimitive.Error>
  );
}

function MessageStoppedRun() {
  const aui = useAui();
  const hasTextPart = useAuiState((s) =>
    s.message.parts.some((p) => p.type === "text"),
  );
  const words = useAuiState((s) =>
    s.message.parts
      .filter((p) => p.type === "text")
      .map((p) => (p as { text: string }).text)
      .join(" "),
  );
  return (
    <StoppedRun
      words={hasTextPart ? [] : words.split(/\s+/).filter(Boolean)}
      reason="Stopped"
      onContinue={() => aui.message.reload()}
      onDiscard={() => aui.message.delete()}
    />
  );
}

function MessageThinking() {
  return <ThinkingIndicator label="Thinking" />;
}

function formatDuration(ms: number): string {
  const totalSeconds = ms / 1000;
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round(totalSeconds - minutes * 60);
  return `${minutes}m ${seconds}s`;
}

function MessageTimer({ message }: { message: TimedMessage }) {
  const isRunning = useAuiState((s) => s.message.status?.type === "running");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!isRunning) return;
    const id = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(id);
  }, [isRunning]);
  if (!isRunning && message.duration_ms == null) return null;
  const start =
    message.started_at ??
    (message.createdAt instanceof Date ? message.createdAt.getTime() : Date.now());
  const elapsed = isRunning ? now - start : message.duration_ms ?? 0;
  return (
    <span className="inline-flex items-center gap-1" data-testid="message-duration">
      {isRunning && (
        <span className="h-1.5 w-1.5 rounded-full bg-[#1D9E75] animate-pulse" aria-hidden />
      )}
      {formatDuration(elapsed)}
    </span>
  );
}

function MessageFooter({ message }: { message: TimedMessage }) {
  const caps = useRtaiCapabilities();
  const modelLabel =
    caps?.models?.find((m) => m.id === caps.selected.model)?.label ??
    caps?.selected.model ??
    null;
  return (
    <div
      className="flex items-center justify-between gap-2 pt-1 text-[12px] text-muted-foreground"
      data-testid="message-footer"
    >
      <div className="flex items-center gap-3 min-w-0">
        {modelLabel && (
          <span className="inline-flex items-center gap-1 truncate" data-testid="message-model">
            <span className="h-2 w-2 rounded-full bg-primary" aria-hidden />
            {modelLabel}
          </span>
        )}
        <MessageTimer message={message} />
        {message.createdAt && (
          <span data-testid="message-date">
            {message.createdAt.toLocaleString(undefined, {
              month: "short",
              day: "numeric",
              hour: "numeric",
              minute: "numeric",
            })}
          </span>
        )}
      </div>
      <ActionBarPrimitive.Root
        autohide="never"
        hideWhenRunning={false}
        className="flex items-center gap-1"
      >
        <ActionBarPrimitive.Reload aria-label="Regenerate" className={footerActionClass}>
          <RotateCw className="h-3.5 w-3.5" />
        </ActionBarPrimitive.Reload>
        <ActionBarPrimitive.Copy
          copiedDuration={2000}
          aria-label="Copy message"
          className={footerActionClass}
        >
          <Check className="h-3.5 w-3.5 text-status-success hidden group-data-[copied=true]:block" />
          <Copy className="h-3.5 w-3.5 group-data-[copied=true]:hidden" />
        </ActionBarPrimitive.Copy>
        <ActionBarPrimitive.ExportMarkdown
          filename="message.md"
          aria-label="Export markdown"
          className={footerActionClass}
        >
          <FileDown className="h-3.5 w-3.5" />
        </ActionBarPrimitive.ExportMarkdown>
      </ActionBarPrimitive.Root>
    </div>
  );
}

export function MessageItem({ message }: { message: ThreadMessage }) {
  // Guards are computed unconditionally (rules of hooks) before the role branch.
  const hasReasoning = useAuiState((s) =>
    s.message.parts.some((p) => p.type === "reasoning"),
  );
  const hasTool = useAuiState((s) =>
    s.message.parts.some((p) => p.type === "tool-call"),
  );
  const hasResponse = useAuiState((s) =>
    s.message.parts.some(
      (p) =>
        (p.type === "text" && (p.text ?? "").trim() !== "") ||
        p.type === "image" ||
        p.type === "file",
    ),
  );

  const isRunning = useAuiState((s) => s.message.status?.type === "running");

  if (message.role === "user") {
    return (
      <MessagePrimitive.Root className="flex gap-3 py-2 flex-row-reverse">
        <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold shrink-0 bg-surface-muted text-surface-muted-foreground">U</div>
        <div className="max-w-[75%] self-end rounded-xl p-2.5 text-[0.9375rem] leading-relaxed bg-chat-user-message-bg border border-primary/20 overflow-wrap-break-word">
          <MessagePrimitive.Parts />
        </div>
      </MessagePrimitive.Root>
    );
  }

  return (
    <MessagePrimitive.Root className="relative flex gap-3 py-2">
      <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold shrink-0 bg-primary text-primary-foreground">AI</div>
      <div className="w-full flex flex-col gap-2">
        {/* Reasoning card — thinking is pulled into its own card above the response
            so it never merges with the answer or tool activity. */}
        {hasReasoning && (
          <div className="bg-card border border-border rounded-xl p-2.5">
            <MessagePrimitive.GroupedParts
              groupBy={groupPartByType({ reasoning: ["group-reasoning"] })}
              indicator="never"
            >
              {({ part, children }) => {
                // Official leaf renderer: each reasoning leaf part carries its
                // streamed text in the part context; <Reasoning /> reads it
                // from there (pinned GroupedParts contract — leaves render
                // the part directly).
                if (part.type === "reasoning") return <Reasoning {...part} />;
                if (part.type !== "group-reasoning") return null;
                const running = part.status.type === "running";
                return (
                  <ReasoningRoot streaming={running}>
                    <ReasoningTrigger active={running} />
                    <ReasoningContent aria-busy={running}>
                      <ReasoningText>{children}</ReasoningText>
                    </ReasoningContent>
                  </ReasoningRoot>
                );
              }}
            </MessagePrimitive.GroupedParts>
          </div>
        )}

        {/* Tool card — tool activity is its own distinct block (modern chat apps),
            never buried inside the response. */}
        {hasTool && (
          <div className="bg-card border border-border rounded-xl p-2.5">
            <MessagePrimitive.GroupedParts
              groupBy={groupPartByType({ "tool-call": ["group-tool"] })}
              indicator="never"
            >
              {({ part, children }) => {
                // Active ToolCall renderer: every tool-call leaf routes through
                // RtaiToolFallback, which preserves the official ToolFallback for
                // ordinary calls and bridges RTAI approval-bearing calls to the
                // concurrent permission REST endpoint. Nothing else renders a tool
                // UI, so nothing is rendered twice.
                if (part.type === "tool-call") {
                  return <RtaiToolFallback {...part} />;
                }
                if (part.type !== "group-tool") return null;
                return (
                  <ToolGroupRoot variant="ghost">
                    <ToolGroupTrigger
                      count={part.indices.length}
                      active={part.status.type === "running"}
                    />
                    <ToolGroupContent>{children}</ToolGroupContent>
                  </ToolGroupRoot>
                );
              }}
            </MessagePrimitive.GroupedParts>
          </div>
        )}

        {/* Response card — final answer text, images, files. Reasoning and
            tool-calls are owned by their own cards above, so they render null here
            to avoid duplication. */}
        {(hasResponse || isRunning) && (
          <div className="bg-card border border-border rounded-xl p-2.5">
            <MessagePrimitive.GroupedParts
              groupBy={groupPartByType({})}
              indicator="always"
            >
              {({ part }) => {
                switch (part.type) {
                  case "text":
                    return <MarkdownTextWrapper />;
                  case "image":
                    return <Image {...part} />;
                  case "file":
                    return <File {...part} />;
                  case "indicator":
                    return <MessageThinking />;
                  case "group-tool":
                  case "tool-call":
                  case "reasoning":
                    return null;
                  default:
                    return null;
                }
              }}
            </MessagePrimitive.GroupedParts>
          </div>
        )}

        {/* Message-level status: error, cancelled run, and the empty-running
            "Thinking" indicator. Rendered at column level so they show even when
            no content card is present. */}
        <MessageError />
        <AuiIf
          condition={(s) =>
            s.message.status?.type === "incomplete" &&
            s.message.status?.reason === "cancelled"
          }
        >
          <MessageStoppedRun />
        </AuiIf>

        {/* Response footer: model · live/elapsed time · date (left); official
            assistant-ui action buttons (reload / copy / export) on the right. No
            custom action components. */}
        <MessageFooter message={message} />
      </div>
    </MessagePrimitive.Root>
  );
}
