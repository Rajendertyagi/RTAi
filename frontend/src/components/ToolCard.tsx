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
    <div className="my-2 rounded-lg border border-tools-border bg-tools-background overflow-hidden">
      {/* Collapsed row */}
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-tools-header-hover rounded-lg cursor-pointer"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        <span
          className="shrink-0 w-5 h-5 flex items-center justify-center text-tools-icon"
          aria-hidden="true"
        >
          <Icon className="h-4 w-4" />
        </span>
        <span className="flex-1 truncate text-sm font-medium text-tools-title">
          {toolName}
        </span>
        {preview && (
          <span className="hidden min-w-0 flex-1 truncate text-sm text-tools-description sm:block">
            {preview}
          </span>
        )}
        <span className="ml-auto text-xs text-surface-muted-foreground">
          {expanded ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </span>
      </button>

      {/* Expanded output */}
      {expanded && (
        <div className="border-t border-interactive">
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-1.5 text-xs text-surface-muted-foreground">
            <span>{toolName}</span>
            <span className="capitalize">{status?.type ?? "running"}</span>
          </div>

          {/* Args */}
          {args && Object.keys(args).length > 0 && (
            <div className="px-3 py-2">
              <pre className="overflow-x-auto text-xs text-surface-muted-foreground">
                {JSON.stringify(args, null, 2)}
              </pre>
            </div>
          )}

          {/* Result */}
          {resultText && (
            <div className="border-t border-interactive">
              <pre className="overflow-x-auto p-3 text-sm font-mono text-surface-foreground">
                {resultText}
              </pre>
            </div>
          )}

          {/* Status indicator */}
          {status?.type === "running" && (
            <div className="flex items-center gap-2 px-3 py-2 text-sm text-surface-muted-foreground">
              <span className="animate-[busy-pulse_1.2s_ease-in-out_infinite]">●</span> Running...
            </div>
          )}
        </div>
      )}
    </div>
  );
};
