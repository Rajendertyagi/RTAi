"use client";

import { MessagePrimitive } from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import type { TextMessagePartProps, ThreadMessage } from "@assistant-ui/react";
import { ToolCard } from "./ToolCard";

// MarkdownTextPrimitive reads text from React context (TextMessagePartProvider)
// and its props are incompatible with TextMessagePartProps. We must not spread
// the part props ╬ô├ç├╢ instead render it without props so it reads from context.
function MarkdownTextWrapper(_props: TextMessagePartProps) {
  // Render inside .message__content so the rich markdown styles in styles.css
  // (headings, lists, links, blockquote, code, tables) apply. Do NOT spread the
  // part props onto MarkdownTextPrimitive; it reads text from context.
  return (
    <div className="message__content">
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
      <MessagePrimitive.Root className="msg-row user">
        <div className="avatar avatar--user">U</div>
        <div className="bubble bubble--user">
          <MessagePrimitive.Parts />
        </div>
      </MessagePrimitive.Root>
    );
  }

  return (
    <MessagePrimitive.Root className="msg-row">
      <div className="avatar avatar--ai">AI</div>
      <div className="bubble bubble--assistant">
        <MessagePrimitive.Parts components={messagePartsComponents} />
      </div>
    </MessagePrimitive.Root>
  );
}
