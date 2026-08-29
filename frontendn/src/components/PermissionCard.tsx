import { useMemo } from "react";
import { useChat } from "../state/ChatContext";
import type { PermissionRequest, ToolContent } from "../types/protocol";
import { useColorScheme } from "../hooks/useColorScheme";
import { CodeBlock } from "./CodeBlock";
import { DiffPreview } from "./DiffPreview";
import { ToolIcon } from "./Icons";

function commandFromRawInput(rawInput: unknown): string | null {
  if (typeof rawInput === "string") return rawInput;
  if (rawInput && typeof rawInput === "object") {
    const obj = rawInput as Record<string, unknown>;
    if (typeof obj.command === "string") return obj.command;
    if (typeof obj.content === "string") return obj.content;
  }
  return null;
}

function diffFromContent(
  content?: ToolContent[],
): { path: string; oldText?: string; newText: string } | null {
  if (!content) return null;
  const block = content.find((c) => c.type === "diff");
  if (!block || block.type !== "diff") return null;
  return { path: block.path, oldText: block.oldText, newText: block.newText };
}

function textFromContent(content?: ToolContent[]): string {
  if (!content) return "";
  return content
    .filter((c): c is { type: "content"; text?: string } => c.type === "content")
    .map((c) => c.text ?? "")
    .join("");
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

export function PermissionCard({
  permission,
  cwd,
}: {
  permission: PermissionRequest;
  cwd: string;
}) {
  const { respondPermission } = useChat();
  const scheme = useColorScheme();
  const name = permission.title ?? permission.kind ?? "tool";
  const command = commandFromRawInput(permission.raw_input);
  const diff = diffFromContent(permission.content);
  const outputText = textFromContent(permission.content);

  const rawPreview = useMemo(() => {
    if (command || diff || outputText || permission.raw_input === undefined) return null;
    try {
      return JSON.stringify(permission.raw_input, null, 2);
    } catch {
      return String(permission.raw_input);
    }
  }, [command, diff, outputText, permission.raw_input]);

  return (
    <div className="permission-dialog">
      <div className="permission-header">
        <ToolIcon kind={permission.kind} />
        <span className="permission-title">Permission required</span>
        <span className="permission-tool">{name}</span>
      </div>

      {command && (
        <div className="permission-detail">
          <CodeBlock code={command} language="bash" complete={true} scheme={scheme} />
        </div>
      )}
      {diff && (
        <div className="permission-detail">
          <DiffPreview
            oldText={diff.oldText}
            newText={diff.newText}
            path={relativePath(diff.path, cwd)}
          />
        </div>
      )}
      {outputText && <pre className="permission-detail-text">{outputText}</pre>}
      {rawPreview && <pre className="permission-detail-text">{rawPreview}</pre>}

      <div className="permission-options">
        {permission.options.map((o) => (
          <button
            key={o.id}
            className="permission-option"
            type="button"
            onClick={() => respondPermission(permission.permission_request_id, o.id)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}