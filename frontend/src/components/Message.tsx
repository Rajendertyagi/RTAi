"use client";

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
import { Copy, Check } from "lucide-react";

// Official Assistant UI Elements (registry-copied at immutable commit
// b6e7ab88b5e6e60866695d31a08adc3a80f449ff, pinned to @assistant-ui/react@0.15.17).
import {
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
import { RtaiToolFallback } from "./assistant-ui/rtai-tool-fallback";
import { Image } from "./assistant-ui/image";
import { File } from "./assistant-ui/file";
import { MarkdownText } from "./assistant-ui/markdown-text";
import { ErrorState } from "./assistant-ui/elements/error-state";
import { StoppedRun } from "./assistant-ui/elements/stopped-run";
import { ThinkingIndicator } from "./assistant-ui/elements/thinking-indicator";

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

export function MessageItem({ message }: { message: ThreadMessage }) {
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
      <div className="w-full bg-card border border-border rounded-xl p-2.5 relative group">
        {/* Official Assistant UI grouping: MessagePrimitive.GroupedParts coalesces
            consecutive reasoning and tool-call parts into native group nodes. Each
            node is rendered with the official Element composition — no custom
            group/leaf wrappers. The official ToolFallback owns generic tool
            rendering (including approval via respondToApproval); part.toolUI owns
            any registered per-tool renderer. */}
        <MessagePrimitive.GroupedParts
          groupBy={groupPartByType({
            reasoning: ["group-reasoning"],
            "tool-call": ["group-tool"],
          })}
        >
          {({ part, children }) => {
            switch (part.type) {
              case "group-reasoning": {
                const running = part.status.type === "running";
                return (
                  <ReasoningRoot streaming={running}>
                    <ReasoningTrigger active={running} />
                    <ReasoningContent aria-busy={running}>
                      <ReasoningText>{children}</ReasoningText>
                    </ReasoningContent>
                  </ReasoningRoot>
                );
              }
              case "group-tool":
                return (
                  <ToolGroupRoot variant="ghost">
                    <ToolGroupTrigger
                      count={part.indices.length}
                      active={part.status.type === "running"}
                    />
                    <ToolGroupContent>{children}</ToolGroupContent>
                  </ToolGroupRoot>
                );
              case "text":
                return <MarkdownTextWrapper />;
              case "reasoning":
                // Ungrouped reasoning leaf: the official Reasoning element's
                // renderer is `() => <MarkdownText />`, so render the same
                // context-driven markdown directly.
                return <MarkdownText />;
              case "tool-call":
                // Official Thread contract: prefer a registered tool UI (toolUI),
                // otherwise the official ToolFallback (which itself calls
                // respondToApproval for approval gates).
                return part.toolUI ?? <RtaiToolFallback {...part} />;
              case "image":
                return <Image {...part} />;
              case "file":
                return <File {...part} />;
              case "indicator":
                return null;
              default:
                return null;
            }
          }}
        </MessagePrimitive.GroupedParts>

        {/* Official message status elements: runtime error, cancelled run,
            and the empty-running "Thinking" indicator. Wired with the
            official MessagePrimitive.Error / ErrorPrimitive gate and the
            message-scope reload()/delete() methods (no custom REST). */}
        <MessageError />
        <AuiIf
          condition={(s) =>
            s.message.status?.type === "incomplete" &&
            s.message.status?.reason === "cancelled"
          }
        >
          <MessageStoppedRun />
        </AuiIf>
        <AuiIf
          condition={(s) =>
            s.message.role === "assistant" &&
            s.message.status?.type === "running" &&
            !s.message.parts.some(
              (p) =>
                p.type === "text" ||
                p.type === "reasoning" ||
                p.type === "tool-call",
            )
          }
        >
          <MessageThinking />
        </AuiIf>

        {/* Copy button — floats on hover, hidden on non-last messages */}
        <ActionBarPrimitive.Root
          hideWhenRunning
          autohide="not-last"
          autohideFloat="single-branch"
          className="absolute -top-2 -right-2 flex rounded-lg shadow-sm opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity"
        >
          <ActionBarPrimitive.Copy
            copiedDuration={2000}
            aria-label="Copy message"
            className="group flex h-7 w-7 items-center justify-center rounded-md bg-surface-elevated border border-border text-muted-foreground hover:text-foreground hover:bg-interactive-hover transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-interactive-focus-ring"
          >
            <Check className="h-3.5 w-3.5 text-status-success hidden group-data-[copied=true]:block" />
            <Copy className="h-3.5 w-3.5 group-data-[copied=true]:hidden" />
          </ActionBarPrimitive.Copy>
        </ActionBarPrimitive.Root>
      </div>
    </MessagePrimitive.Root>
  );
}
