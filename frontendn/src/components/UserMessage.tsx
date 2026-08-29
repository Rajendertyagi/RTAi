import { MessagePrimitive } from "@assistant-ui/react";

export function UserMessage() {
  return (
    <MessagePrimitive.Root className="message user">
      <div className="avatar">U</div>
      <div className="bubble">
        <MessagePrimitive.Parts>
          {({ part }) => {
            if (part.type === "text") return <span>{part.text}</span>;
            return null;
          }}
        </MessagePrimitive.Parts>
      </div>
    </MessagePrimitive.Root>
  );
}