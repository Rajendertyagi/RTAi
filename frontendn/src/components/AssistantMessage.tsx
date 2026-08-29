import { MessagePrimitive } from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import remarkGfm from "remark-gfm";
import { useChat } from "../state/ChatContext";
import { ReasoningBlock } from "./ReasoningBlock";
import { ToolCard } from "./ToolCard";
import { PermissionCard } from "./PermissionCard";

/**
 * Assistant message: renders each part in chronological order. Reasoning parts
 * collapse to a summary once complete; tool-call parts render as smart cards;
 * text parts render as markdown. A pending permission dialog (message-level
 * RTAI state) renders after the parts.
 */
export function AssistantMessage({ messageId }: { messageId: string }) {
  const { state } = useChat();
  const original = state.messages.find((m) => m.id === messageId);
  const permission = original?.permission;
  const isError = original?.role === "error";

  return (
    <MessagePrimitive.Root className={`message agent${isError ? " error" : ""}`}>
      <div className="avatar">{isError ? "⚠" : "AI"}</div>
      <div className="bubble">
        <MessagePrimitive.Parts>
          {({ part }) => {
            switch (part.type) {
              case "reasoning":
                return <ReasoningBlock part={part} />;
              case "tool-call":
                return <ToolCard part={part} />;
              case "text":
                if (part.text === "" && part.status?.type === "running") {
                  return (
                    <div className="thinking-dots" aria-label="Thinking">
                      <span />
                      <span />
                      <span />
                    </div>
                  );
                }
                return (
                  <MarkdownTextPrimitive
                    className="aui-md"
                    remarkPlugins={[remarkGfm]}
                    smooth={false}
                  />
                );
              default:
                return null;
            }
          }}
        </MessagePrimitive.Parts>
        {permission && <PermissionCard permission={permission} cwd={state.cwd} />}
      </div>
    </MessagePrimitive.Root>
  );
}