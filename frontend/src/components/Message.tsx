"use client";

import {
  MessagePrimitive,
  groupPartByType,
  ActionBarPrimitive,
  type ThreadMessage,
} from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import { Copy, Check } from "lucide-react";
import { RtaiToolFallback } from "./assistant-ui/rtai-tool-fallback";

// MarkdownTextPrimitive reads text from React context (TextMessagePartProvider)
// and its props are incompatible with TextMessagePartProps. We must not spread
// the part props instead render it without props so it reads from context.
function MarkdownTextWrapper() {
  return (
    <div className="text-[0.9375rem] leading-relaxed text-surface-foreground overflow-wrap-break-word">
      <MarkdownTextPrimitive />
    </div>
  );
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
        {/* Native Assistant UI grouping (pinned 0.15.17): MessagePrimitive.GroupedParts
            coalesces consecutive reasoning + tool-call parts into one "Thinking" run
            and renders every node through this single render callback. This is the
            official 0.15.17 API — there is NO standalone Reasoning/ToolGroup component
            in this version; defaultComponents.ToolGroup/ReasoningGroup are bare
            ({children}) => children pass-throughs. So group nodes simply return the
            rendered subtree (mirroring the native bare defaults) and only leaves that
            have no native styled renderer get a minimal component. */}
        <MessagePrimitive.GroupedParts
          groupBy={groupPartByType({
            reasoning: ["group-chainOfThought", "group-reasoning"],
            "tool-call": ["group-chainOfThought", "group-tool"],
          })}
        >
          {({ part, children }) => {
            switch (part.type) {
              // Group nodes: delegate to the framework-rendered subtree. No
              // custom wrapper/state — this mirrors native defaultComponents.
              case "group-chainOfThought":
              case "group-reasoning":
              case "group-tool":
                return children;
              case "text":
                return <MarkdownTextWrapper />;
              case "reasoning":
                // No native styled reasoning component in 0.15.17
                // (defaultComponents.Reasoning renders nothing), so a minimal
                // leaf renderer is required to display the thinking text.
                return (
                  <div className="text-sm text-muted-foreground italic py-0.5">
                    {typeof part.text === "string" ? part.text : ""}
                  </div>
                );
              case "tool-call": {
                // toolUI is the framework-provided registered tool UI (native);
                // RtaiToolFallback is only the backend REST approval bridge,
                // used when no native tool UI is registered.
                const { toolUI, ...toolProps } = part;
                return toolUI ?? <RtaiToolFallback {...toolProps} />;
              }
              case "image":
                // No native styled Image component in 0.15.17; minimal leaf.
                return part.image ? (
                  <img
                    src={part.image}
                    alt={part.filename ?? "image"}
                    className="my-1.5 max-h-80 rounded-lg border border-border object-contain"
                  />
                ) : null;
              case "file":
                // No native styled File component in 0.15.17; minimal leaf.
                return (
                  <div className="my-1.5 rounded-lg border border-border bg-surface px-3 py-2 text-xs text-muted-foreground">
                    {part.filename ?? part.mimeType ?? "file attachment"}
                  </div>
                );
              case "indicator":
                return null;
              default:
                return null;
            }
          }}
        </MessagePrimitive.GroupedParts>

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
