import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useChat } from "../state/ChatContext";
import type { Message } from "../types/protocol";

const TOOL_LABEL: Record<string, string> = {
  pending: "Queued",
  running: "Running",
  success: "Done",
  error: "Failed",
  cancelled: "Cancelled",
};

export function MessageBubble({ message }: { message: Message }) {
  const { respondPermission } = useChat();

  const avatar = message.role === "user" ? "U" : message.role === "agent" ? "AI" : "⚠";

  return (
    <div className={`message ${message.role}`}>
      <div className="avatar">{avatar}</div>
      <div className="bubble">
        {message.role === "agent" ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text}</ReactMarkdown>
        ) : (
          message.text
        )}

        {message.tools && message.tools.length > 0 && (
          <div className="tool-timeline">
            {message.tools.map((t) => (
              <div key={t.id} className={`tool-call ${t.status}`}>
                <span className="tool-title">{t.title}</span>
                <span className="tool-status">{TOOL_LABEL[t.status] ?? t.status}</span>
              </div>
            ))}
          </div>
        )}

        {message.permission && (
          <div className="permission-dialog">
            <div className="permission-title">Permission required</div>
            <div className="permission-options">
              {message.permission.options.map((o) => (
                <button
                  key={o.id}
                  className="permission-option"
                  type="button"
                  onClick={() => respondPermission(message.permission!.permission_request_id, o.id)}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
