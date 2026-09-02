"use client";

import {
  AttachmentPrimitive,
  ComposerPrimitive,
  useAui,
  useAuiState,
  } from "@assistant-ui/react";
import { ArrowUp, Paperclip, Square, X } from "lucide-react";
import { CapabilityControls } from "./CapabilitySelectors";
import { useRtaiTransportState } from "./useRtaiTransportState";


export function Composer() {
  const aui = useAui();
  // Official transport running state: connection isSending (via thread) or backend status === "running"
  // Send/Stop depend only on official runtime; permissions not migrated this phase.
  const transportStatusRunning = useRtaiTransportState("status", "ready") === "running";
  const threadRunning = useAuiState((s) => s.thread?.isRunning ?? false);
  const isRunning = transportStatusRunning || threadRunning;
  const handleCancel = () => aui.thread().cancelRun();

  return (
    <div
      className="w-full min-w-0 overflow-visible rounded-xl border border-interactive bg-surface-elevated focus-within:ring-2 focus-within:ring-interactive-focus-ring"
      data-testid="composer"
    >
      <ComposerPrimitive.Root>
        <ComposerPrimitive.AttachmentDropzone className="rounded-xl">
          <ComposerPrimitive.Attachments>
            {({ attachment }) => (
              <div
                key={attachment.id}
                className="m-3 mb-0 flex items-center gap-2 rounded-lg border border-interactive bg-surface p-2"
              >
                {attachment.type === "image" && attachment.content?.[0]?.type === "image" ? (
                  <img
                    src={attachment.content?.[0]?.image}
                    alt={attachment.name}
                    className="h-10 w-10 rounded object-cover"
                  />
                ) : (
                  <span className="truncate text-xs text-muted-foreground">
                    {attachment.name}
                  </span>
                )}
                <AttachmentPrimitive.Remove
                  className="ml-auto rounded-md p-1 text-muted-foreground transition-colors hover:bg-interactive-hover hover:text-foreground"
                  aria-label="Remove attachment"
                >
                  <X className="h-3.5 w-3.5" />
                </AttachmentPrimitive.Remove>
              </div>
            )}
          </ComposerPrimitive.Attachments>
          <div className="flex items-end gap-2 p-3">
            <ComposerPrimitive.Input
              placeholder="Ask anything…"
              rows={1}
              onInput={(e) => {
                const el = e.currentTarget as HTMLTextAreaElement;
                el.style.height = "auto";
                el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
              }}
              className="max-h-[200px] flex-1 resize-none overflow-y-auto border-0 bg-transparent px-1 py-1.5 text-sm text-foreground outline-none placeholder:text-muted-foreground"
              data-testid="composer-input"
            />
            {isRunning ? (
              <button
                type="button"
                onClick={handleCancel}
                aria-label="Stop generation"
                data-testid="composer-stop"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-status-error text-status-error-foreground transition-opacity hover:opacity-85"
              >
                <Square className="h-4 w-4" fill="currentColor" />
              </button>
            ) : (
              <ComposerPrimitive.Send
                data-testid="composer-send"
                aria-label="Send message"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <ArrowUp className="h-4 w-4" />
              </ComposerPrimitive.Send>
            )}
          </div>
        </ComposerPrimitive.AttachmentDropzone>
        <div className="flex items-center justify-between gap-2 px-3 pb-2">
          <CapabilityControls />
          <ComposerPrimitive.AddAttachment
            aria-label="Attach file"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-interactive-hover hover:text-foreground"
          >
            <Paperclip className="h-4 w-4" />
          </ComposerPrimitive.AddAttachment>
        </div>
      </ComposerPrimitive.Root>
    </div>
  );
}
