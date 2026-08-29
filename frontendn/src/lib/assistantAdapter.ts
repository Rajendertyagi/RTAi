import {
  useExternalStoreRuntime,
  type AppendMessage,
  type ThreadAssistantMessagePart,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import type { ReadonlyJSONObject } from "assistant-stream/utils";
import { useChat } from "../state/ChatContext";
import type { Message, MessagePart } from "../types/protocol";

/**
 * Bridge between the RTAI chat state (ChatContext) and the assistant-ui
 * external-store runtime.
 *
 * The RTAI reducer is the single source of truth for messages. This module
 * only converts RTAI `Message` objects into assistant-ui `ThreadMessageLike`
 * shapes and forwards composer actions (send/cancel) back into ChatContext.
 */

/**
 * ACP tool arguments are `unknown` (often a string for bash commands), while
 * assistant-ui requires a JSON object. Non-object inputs are stashed in
 * `argsText` and `args` is left empty so the runtime never has to parse them.
 */
function argsFromRawInput(rawInput: unknown): { args: ReadonlyJSONObject; argsText: string } {
  if (rawInput !== null && typeof rawInput === "object" && !Array.isArray(rawInput)) {
    return {
      args: rawInput as ReadonlyJSONObject,
      argsText: JSON.stringify(rawInput, null, 2),
    };
  }
  const text =
    typeof rawInput === "string" ? rawInput : JSON.stringify(rawInput ?? {}, null, 2);
  return { args: {}, argsText: text };
}

function convertPart(part: MessagePart): ThreadAssistantMessagePart | null {
  switch (part.type) {
    case "text":
      return { type: "text", text: part.text };
    case "reasoning":
      return { type: "reasoning", text: part.text };
    case "tool": {
      const tool = part.tool;
      if (!tool) return null;
      const { args, argsText } = argsFromRawInput(tool.rawInput);
      return {
        type: "tool-call",
        toolCallId: tool.id,
        toolName: tool.title ?? tool.kind ?? "tool",
        args,
        argsText,
        // The full RTAI ToolCall rides along as the artifact so the tool card
        // can render locations/kind/status without re-deriving them.
        artifact: tool,
        result: tool.content,
        isError: tool.status === "error",
      };
    }
    default:
      return null;
  }
}

export function convertMessage(message: Message): ThreadMessageLike {
  if (message.role === "user") {
    return {
      id: message.id,
      role: "user",
      content: [{ type: "text", text: message.text }],
    };
  }

  // The backend emits parts for every turn; the text blob is the fallback for
  // messages that arrived before part events were wired up.
  const hasParts = Boolean(message.parts && message.parts.length > 0);
  const content: readonly ThreadAssistantMessagePart[] = hasParts
    ? message.parts!.map(convertPart).filter(
        (p): p is ThreadAssistantMessagePart => p !== null,
      )
    : [{ type: "text" as const, text: message.text }];

  const status =
    message.status === "streaming"
      ? { type: "running" as const }
      : message.status === "error"
        ? { type: "incomplete" as const, reason: "error" as const }
        : { type: "complete" as const, reason: "stop" as const };

  return {
    id: message.id,
    role: "assistant",
    content,
    status,
  };
}

export function useAssistantRuntime() {
  const { state, sendPrompt, cancel } = useChat();

  const onNew = async (message: AppendMessage) => {
    if (message.content.length !== 1 || message.content[0]?.type !== "text") {
      throw new Error("Only text content is supported");
    }
    // ChatContext adds the user message optimistically and sends the prompt.
    sendPrompt(message.content[0].text);
  };

  const onCancel = async () => {
    cancel();
  };

  return useExternalStoreRuntime<Message>({
    messages: state.messages,
    isRunning: state.generating,
    convertMessage,
    onNew,
    onCancel,
  });
}