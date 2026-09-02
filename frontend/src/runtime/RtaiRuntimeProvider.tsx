"use client";

import {
  AssistantRuntimeProvider,
  useAssistantTransportRuntime,
  useAuiState,
  unstable_createMessageConverter,
  AuiConfig,
  Suggestions,
  type AssistantTransportConnectionMetadata,
} from "@assistant-ui/react";
import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";
import type { ReadonlyJSONObject } from "assistant-stream/utils";
import { WELCOME_SUGGESTIONS } from "../data/welcomeSuggestions";
import { RtaiImageAttachmentAdapter } from "./rtaiImageAttachmentAdapter";
import type { BackendMessage, RtaiAssistantState } from "../types/rtaiAssistantState";
// Side-effect import: activates the official AssistantTransport command + state
// augmentation (Assistant.Commands / Assistant.ExternalState) used below.
import "../types/assistantTransportAugmentation";

/**
 * Runtime provider migrated to official AssistantTransport.
 *
 * Browser → POST /assistant → Python assistant-stream → existing ACP/OpenCode adapter.
 * No WebSocket is opened from the active runtime.
 *
 * Verified against locked @assistant-ui/react@0.15.17:
 * - useAssistantTransportRuntime, AssistantTransportConnectionMetadata, useAssistantTransportState,
 *   unstable_createMessageConverter all exported via index.d.ts / assistant-transport.js
 */

const RTAI_CONFIG = AuiConfig({
  suggestions: Suggestions(WELCOME_SUGGESTIONS),
});

const getInitialCwd = (): string | undefined => {
  if (typeof window === "undefined") return undefined;
  const v = localStorage.getItem("project-folder");
  return v && v.trim() ? v.trim() : undefined;
};

// Derived source-message union for the official converter. Authoritative backend
// messages already carry stable ids; pending add-message commands supply
// `{ role, parts }` with no id (pinned AddMessageCommand.message), so the
// converter assigns its positional fallback id for them.
type PendingCommand =
  AssistantTransportConnectionMetadata["pendingCommands"][number];
type PendingAddMessage = Extract<PendingCommand, { type: "add-message" }>["message"];
type ConverterSourceMessage = BackendMessage | PendingAddMessage;

const messageConverter = unstable_createMessageConverter<ConverterSourceMessage>(
  (msg) => {
    const content = msg.parts.map((p) => {
      if (p.type === "tool-call") {
        const approval = p.approval;
        return {
          type: "tool-call" as const,
          toolCallId: p.toolCallId,
          toolName: p.toolName,
          args: p.args as ReadonlyJSONObject,
          argsText: p.argsText,
          ...(p.result !== undefined && { result: p.result }),
          ...(p.isError !== undefined && { isError: p.isError }),
          ...(p.artifact !== undefined && { artifact: p.artifact }),
          // Forward the official Assistant UI approval state; Assistant UI derives
          // requires-action from the approval field. Map only the exact locked
          // @assistant-ui/core@0.3.16 fields; do not add status or custom fields.
          ...(approval !== undefined && {
            approval: {
              id: approval.id,
              ...(approval.approved !== undefined && { approved: approval.approved }),
              ...(approval.reason !== undefined && { reason: approval.reason }),
              ...(approval.isAutomatic !== undefined && { isAutomatic: approval.isAutomatic }),
              ...(approval.options !== undefined && {
                options: approval.options.map((o) => ({
                  id: o.id,
                  kind: o.kind,
                  ...(o.label !== undefined && { label: o.label }),
                  ...(o.description !== undefined && { description: o.description }),
                })),
              }),
              ...(approval.optionId !== undefined && { optionId: approval.optionId }),
              ...(approval.resolution !== undefined && { resolution: approval.resolution }),
            },
          }),
        };
      }
      if (p.type === "reasoning") {
        return { type: "reasoning" as const, text: p.text };
      }
      if (p.type === "image") {
        return {
          type: "image" as const,
          image: p.image,
        };
      }
      if (p.type === "file") {
        // Pinned @assistant-ui/core FileMessagePart requires `data` and `mimeType`
        // (both string) and has NO `uri` field. The backend supplies both for file
        // parts; the defaults only guard this defensive branch. `uri` is dropped.
        return {
          type: "file" as const,
          data: p.data ?? "",
          mimeType: p.mimeType ?? "application/octet-stream",
          ...(p.filename !== undefined && { filename: p.filename }),
        };
      }
      return { type: "text" as const, text: p.text };
    });

    // BackendMessage carries a stable id; pending add-message messages have no id,
    // so we let unstable_createMessageConverter assign its positional fallback id
    // (FALLBACK_ID_PREFIX + index). markDelivered() clears pendingCommands before
    // the first authoritative state update, so a pending message disappears before
    // its authoritative replacement is visible — no custom dedup is needed.
    if ("id" in msg) {
      return { id: msg.id, role: msg.role, content };
    }
    return { role: msg.role, content };
  },
);

const converter = (
  state: RtaiAssistantState,
  connectionMetadata: AssistantTransportConnectionMetadata,
) => {
  // Optimistic pending add-message commands per official lifecycle.
  // `AddMessageCommand.message` has no `id` (pinned @assistant-ui/core types);
  // the official converter assigns each pending message a positional fallback id.
  // markDelivered() clears pendingCommands before the first authoritative state
  // update lands, so a pending message disappears before its authoritative
  // replacement becomes visible — no custom dedup is needed.
  const pendingMessages = connectionMetadata.pendingCommands.flatMap((c) =>
    c.type === "add-message" ? [c.message] : []
  );

  const allMessages: ConverterSourceMessage[] = [...state.messages, ...pendingMessages];

  // Derive a minimal, READ-ONLY capability-command pending status from the
  // official AssistantTransport connection metadata. We never mutate the
  // authoritative server-projected `rtaiCapabilities`; this flag only tells the
  // UI which capability controls are currently queued/in transit so they can be
  // disabled. The backend idempotently handles any duplicated network request.
  const pendingTypes = connectionMetadata.pendingCommands.map((c) => {
    const t = (c as { type?: unknown }).type;
    return typeof t === "string" ? t : "";
  });
  const hasPending = (t: string) => pendingTypes.includes(t);
  const rtaiCapabilitiesPending = {
    refresh: hasPending("rtai.refreshCapabilities"),
    agent: hasPending("rtai.selectAgent"),
    model: hasPending("rtai.selectModel"),
    mode: hasPending("rtai.selectMode"),
    thinking: hasPending("rtai.selectThinking"),
  };

  return {
    messages: messageConverter.toThreadMessages(allMessages),
    // The external `state` projected to the runtime must be JSON-serializable
    // (ReadonlyJSONValue). It carries the namespaced rtaiCapabilities section from the
    // backend plus the converter-derived rtaiCapabilitiesPending flag. Authoritative
    // messages live in `messages` above and are intentionally NOT mirrored here.
    state: {
      sessionId: state.sessionId ?? null,
      cwd: state.cwd ?? null,
      status: state.status,
      error: state.error ?? null,
      rtaiCapabilities: state.rtaiCapabilities ?? null,
      rtaiCapabilitiesPending,
      rtaiDiagnostics: state.rtaiDiagnostics ?? [],
    },
    isRunning:
      connectionMetadata.isSending || state.status === "running",
  };
};

// --- PART 5: provider-owned session lifecycle (the ONLY RTAI-specific session owner) ---
// Holds a remount epoch, NOT messages/attachments/tool/approval/pending/running state.
// Bumping the epoch remounts the inner AssistantTransport runtime (keyed by epoch), which
// starts a genuinely new backend session without a full page reload. New Chat and cwd
// changes close the old backend session via the DELETE barrier, then bump the epoch.
interface SessionLifecycle {
  resetSession: () => void;
}

const SessionLifecycleContext = createContext<SessionLifecycle | null>(null);

export function useSessionLifecycle(): SessionLifecycle {
  const ctx = useContext(SessionLifecycleContext);
  if (!ctx) {
    throw new Error("useSessionLifecycle must be used within RtaiRuntimeProvider");
  }
  return ctx;
}

function TransportReadyGate({ children }: { children: ReactNode }) {
  // Official readiness signal: the AssistantTransport-backed main thread mounts
  // asynchronously after a placeholder (empty) thread. While that placeholder is
  // active, `thread.isLoading` is true and `useAssistantTransportState` throws
  // (its `thread.extras` lacks the transport symbol). Gate every transport-state
  // consumer behind this single boundary so they only render against the real
  // transport thread.
  const isLoading = useAuiState((s) => s.thread.isLoading);
  if (isLoading) {
    return (
      <div className="flex h-dvh w-full items-center justify-center bg-background text-sm text-muted-foreground">
        Loading assistant…
      </div>
    );
  }
  if (
    typeof window !== "undefined" &&
    typeof window.localStorage !== "undefined" &&
    window.localStorage.getItem("rtai-debug") === "1"
  ) {
    console.debug("[rtai-capability]", "transport-thread-ready");
  }
  return <>{children}</>;
}

function RtaiAssistantRuntime({ children }: { children: ReactNode }) {
  // Fresh per mount: initialState carries NO sessionId, so the backend generates a new
  // session on the first /assistant POST after a remount. Thereafter the sessionId
  // round-trips via the converter's external state. All messages, attachments, queued
  // commands, approvals, running state, and capability state are recreated empty.
  const initialState: RtaiAssistantState = {
    cwd: getInitialCwd(),
    messages: [],
    status: "ready",
  };

  const runtime = useAssistantTransportRuntime<RtaiAssistantState>({
    api: "/assistant",
    // Required by pinned AssistantTransportOptions: headers sent with every
    // /assistant request. No extra headers are needed for this app.
    headers: {},
    initialState,
    converter,
    // Narrow RTAI image adapter enforces the backend MIME allowlist and delegates
    // conversion/send/remove to the official SimpleImageAttachmentAdapter. No second store.
    adapters: { attachments: new RtaiImageAttachmentAdapter() },
    onError: (error, { updateState }) => {
      // Safe error only, via official updateState callback
      updateState((s) => ({
        ...s,
        status: "error" as const,
        error: error.message,
      }));
    },
    onCancel: ({ updateState }) => {
      updateState((s) => ({
        ...s,
        status: "cancelled" as const,
      }));
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime} config={RTAI_CONFIG}>
      <TransportReadyGate>{children}</TransportReadyGate>
    </AssistantRuntimeProvider>
  );
}

export function RtaiRuntimeProvider({ children }: { children: ReactNode }) {
  const [sessionEpoch, setSessionEpoch] = useState(0);
  const resetSession = useCallback(() => setSessionEpoch((e) => e + 1), []);

  return (
    <SessionLifecycleContext.Provider value={{ resetSession }}>
      <RtaiAssistantRuntime key={sessionEpoch}>{children}</RtaiAssistantRuntime>
    </SessionLifecycleContext.Provider>
  );
}
