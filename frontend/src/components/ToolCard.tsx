"use client";

import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Terminal,
  FileText,
  Pencil,
  Search,
  FolderOpen,
  GitBranch,
  Box,
} from "lucide-react";

// Tool icon mapping — extend as needed
const toolIcons: Record<string, typeof Terminal> = {
  bash: Terminal,
  shell: Terminal,
  cmd: Terminal,
  read: FileText,
  view: FileText,
  file_read: FileText,
  edit: Pencil,
  multiedit: Pencil,
  write: Pencil,
  create: Pencil,
  search: Search,
  grep: Search,
  find: Search,
  glob: Search,
  ls: FolderOpen,
  dir: FolderOpen,
  git: GitBranch,
  task: Box,
};

function getToolIcon(toolName: string) {
  const icon = toolIcons[toolName.toLowerCase()] ?? Box;
  return icon;
}

export const ToolCard: ToolCallMessagePartComponent = ({
  args,
  status,
  result,
  toolName,
}) => {
  const [expanded, setExpanded] = useState(false);
  const Icon = getToolIcon(toolName);

  // Extract display path from args
  const displayPath =
    typeof args?.path === "string"
      ? args.path
      : typeof args?.filePath === "string"
      ? args.filePath
      : typeof args?.file_path === "string"
      ? args.file_path
      : undefined;

  // Extract command for bash
  const command = typeof args?.command === "string" ? args.command : undefined;
  const preview = command
    ? command.split("\n")[0].slice(0, 100)
    : displayPath || toolName;

  // Format result text
  const resultText =
    typeof result === "string"
      ? result
      : result
      ? JSON.stringify(result, null, 2).slice(0, 500)
      : "";

  return (
    <div className="tool my-2 rounded-lg border border-[var(--tools-border)] bg-[var(--tools-background)] overflow-hidden">
      {/* Collapsed row */}
      <button
        type="button"
        className="tool__header flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-[var(--tools-header-hover)]"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        <span
          className="tool__icon flex h-5 w-5 items-center justify-center text-[var(--tools-icon)]"
          aria-hidden="true"
        >
          <Icon className="h-4 w-4" />
        </span>
        <span className="tool__title flex-1 truncate text-sm font-medium text-[var(--tools-title)]">
          {toolName}
        </span>
        {preview && (
          <span className="tool__desc hidden min-w-0 flex-1 truncate text-sm text-[var(--tools-description)] sm:block">
            {preview}
          </span>
        )}
        <span className="tool__duration ml-auto text-xs text-[var(--surface-muted-foreground)]">
          {expanded ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </span>
      </button>

      {/* Expanded output */}
      {expanded && (
        <div className="tool__output border-t border-[var(--interactive-border)]">
          {/* Header */}
          <div className="tool__output-header flex items-center justify-between px-3 py-1.5 text-xs text-[var(--surface-muted-foreground)]">
            <span>{toolName}</span>
            <span className="capitalize">{status?.type ?? "running"}</span>
          </div>

          {/* Args */}
          {args && Object.keys(args).length > 0 && (
            <div className="px-3 py-2">
              <pre className="overflow-x-auto text-xs text-[var(--surface-muted-foreground)]">
                {JSON.stringify(args, null, 2)}
              </pre>
            </div>
          )}

          {/* Result */}
          {resultText && (
            <div className="tool__output-pre border-t border-[var(--interactive-border)]">
              <pre className="overflow-x-auto p-3 text-sm font-mono text-[var(--surface-foreground)]">
                {resultText}
              </pre>
            </div>
          )}

          {/* Status indicator */}
          {status?.type === "running" && (
            <div className="flex items-center gap-2 px-3 py-2 text-sm text-[var(--surface-muted-foreground)]">
              <span className="dot-pulse">●</span> Running...
            </div>
          )}
        </div>
      )}
    </div>
  );
};
