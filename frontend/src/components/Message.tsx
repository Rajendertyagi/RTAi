"use client";

import { MessagePrimitive } from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import type { TextMessagePartProps, ThreadMessage } from "@assistant-ui/react";
import { ToolCard } from "./ToolCard";

// MarkdownTextPrimitive reads text from React context (TextMessagePartProvider)
// and its props are incompatible with TextMessagePartProps. We must not spread
// the part props instead render it without props so it reads from context.
function MarkdownTextWrapper(_props: TextMessagePartProps) {
  return (
    <div className="text-[0.9375rem] leading-relaxed text-surface-foreground overflow-wrap-break-word">
      <MarkdownTextPrimitive />
    </div>
  );
}

const messagePartsComponents = {
  Text: MarkdownTextWrapper,
  tools: { Fallback: ToolCard },
} as const;

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
    <MessagePrimitive.Root className="flex gap-3 py-2">
      <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold shrink-0 bg-primary text-primary-foreground">AI</div>
      <div className="w-full bg-card border border-border rounded-xl p-2.5">
        <MessagePrimitive.Parts components={messagePartsComponents} />
      </div>
    </MessagePrimitive.Root>
  );
}
