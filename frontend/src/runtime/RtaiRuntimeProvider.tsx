"use client";

import {
  AssistantRuntimeProvider,
  useAssistantTransportRuntime,
  useAssistantTransportSendCommand,
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
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type MutableRefObject,
} from "react";
import type { ReadonlyJSONObject } from "assistant-stream/utils";
import { WELCOME_SUGGESTIONS } from "../data/welcomeSuggestions";
import { useRtaiSessionId } from "../hooks/useRtaiAssistantState";
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

// --- Durable per-tab session identity (sessionStorage, NEVER localStorage) ---
// Root-cause fix for OpenCode ACP child accumulation across reloads: previously
// every browser reload mounted a runtime whose initialState carried NO sessionId,
// so the first POST /assistant minted a new backend session key and one new
// `opencode.exe acp` child per reload, while old sessions lingered until the
// 30-minute idle timeout. sessionStorage is scoped to this origin AND this
// browser tab, so:
//   - reloading the same tab reuses the same opaque sessionId (no new child),
//   - a different tab never sees this value (deliberate tabs stay isolated),
//   - ONLY the opaque sessionId is ever persisted — no messages, prompts,
//     responses, capability options, model values, credentials, paths, or
//     diagnostics.
// There is deliberately NO unload/beforeunload/pagehide DELETE: reload is the
// main scenario this fixes, and unload deletion would defeat session reuse.
// Abandoned tabs are handled by the backend idle/disconnect lifecycle instead.
const RTAI_SESSION_STORAGE_KEY = "rtai.assistant.sessionId";
// The backend mints sessionId via str(uuid.uuid4()) (models.ensure_state_shape),
// so only well-formed UUIDs are ever hydrated back — junk or foreign values in
// storage are ignored and the backend simply generates a fresh id.
const RTAI_SESSION_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function readStoredSessionId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(RTAI_SESSION_STORAGE_KEY);
    if (typeof raw !== "string" || !RTAI_SESSION_ID_PATTERN.test(raw)) {
      return null;
    }
    return raw;
  } catch {
    return null;
  }
}

function writeStoredSessionId(sessionId: string): void {
  if (typeof window === "undefined") return;
  // Only authoritative, well-formed UUIDs are ever persisted. sessionStorage has
  // no separate "valid" flag, so the only safe rule is: never write a value that
  // fails validation. A malformed, null, empty, or temporary id therefore cannot
  // overwrite or erase an already-valid stored id (the existing value is left
  // untouched), preserving durable same-tab reuse across reloads.
  if (typeof sessionId !== "string" || !RTAI_SESSION_ID_PATTERN.test(sessionId)) {
    return;
  }
  try {
    if (window.sessionStorage.getItem(RTAI_SESSION_STORAGE_KEY) !== sessionId) {
      window.sessionStorage.setItem(RTAI_SESSION_STORAGE_KEY, sessionId);
    }
  } catch {
    // Storage unavailable (e.g. blocked): in-runtime reuse still works via the
    // transport's own state; reloads simply mint fresh sessions as before.
  }
}

function clearStoredSessionId(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(RTAI_SESSION_STORAGE_KEY);
  } catch {
    // ignore: deliberate replacement must never fail because of storage
  }
}

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

// Persists the AUTHORITATIVE backend session identity into per-tab sessionStorage.
// Rendered inside the transport-ready subtree only: the gate guarantees the
// AssistantTransport external state exists, so the single centralized access hook
// (useRtaiSessionId) is safe here. Only the opaque sessionId that authoritative
// streamed state supplies/changes is ever written (never messages, prompts,
// responses, capability options, model values, credentials, paths, or
// diagnostics); a null sessionId writes nothing (nothing authoritative yet).
// sessionStorage is per-tab, so separate tabs never share a session id.
function SessionIdStorageSync() {
  const sessionId = useRtaiSessionId();
  useEffect(() => {
    if (!sessionId) return;
    writeStoredSessionId(sessionId);
  }, [sessionId]);
  return null;
}

function TransportReadyGate({ children }: { children: ReactNode }) {
  // Official readiness signal: the AssistantTransport-backed main thread mounts
  // asynchronously after a placeholder (empty) thread. While that placeholder is
  // active, `thread.isLoading` is true and `useAssistantTransportState` throws
  // (its `thread.extras` lacks the transport symbol). Gate every transport-state
  // consumer behind this single boundary so they only render against the real
  // transport thread.
  const isLoading = useAuiState((s) => s.thread.isLoading);
  const sendCommand = useAssistantTransportSendCommand();
  const gateEmitted = useRef(false);
  useEffect(() => {
    if (!isLoading && !gateEmitted.current) {
      gateEmitted.current = true;
      // Real client event: the transport gate became ready and the main thread
      // is mounted. Sent once via the rtai.clientDiagnostic command; the
      // component-local ref guard prevents duplicate emission on rerender or
      // StrictMode replay. Recorded server-side with origin:"client".
      sendCommand({ type: "rtai.clientDiagnostic", event: "gate_ready" } as Parameters<typeof sendCommand>[0]);
    }
  }, [isLoading, sendCommand]);
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

// Bridges the official useAssistantTransportSendCommand() hook (only callable inside the
// AssistantRuntimeProvider tree) to sendCommandRef, which the error handler (defined in
// RtaiAssistantRuntime's initializer, outside the provider context) reads. Renders nothing;
// stores the hook's returned function into the ref via an effect. No store/context/polling/
// WebSocket/state mutation; never sends during render; never logs error text or payloads.
function SendCommandBridge({
  sendCommandRef,
}: {
  sendCommandRef: MutableRefObject<((cmd: unknown) => void) | null>;
}) {
  const sendCommand = useAssistantTransportSendCommand();
  useEffect(() => {
    sendCommandRef.current = sendCommand as unknown as (cmd: unknown) => void;
  }, [sendCommand, sendCommandRef]);
  return null;
}

function RtaiAssistantRuntime({ children }: { children: ReactNode }) {
  // Durable per-tab session identity: hydrate the opaque sessionId persisted by
  // SessionIdStorageSync from sessionStorage (same origin + same tab ONLY). A
  // browser reload remounts this runtime with the SAME backend session key, so
  // the first POST /assistant reuses the existing adapter instead of spawning
  // another opencode.exe child. No client-side random generation happens here:
  // when no valid stored id exists, the backend mints one
  // (models.ensure_state_shape) and streams it back; SessionIdStorageSync then
  // persists it for the next reload. Deliberate replacement (New Chat / cwd
  // change) clears the stored id via resetSession() BEFORE this remount, so a
  // fresh session is guaranteed there. All messages, attachments, queued
  // commands, approvals, running state, and capability state are still
  // recreated empty on every mount.
  const initialState: RtaiAssistantState = {
    sessionId: readStoredSessionId() ?? undefined,
    cwd: getInitialCwd(),
    messages: [],
    status: "ready",
  };

  // Holds the official sendCommand function (from useAssistantTransportSendCommand,
  // wired by SendCommandBridge rendered inside AssistantRuntimeProvider) so the
  // error handler (defined in this initializer, outside the provider context) can
  // emit diagnostics via the same rtai.clientDiagnostic command path.
  const sendCommandRef = useRef<((cmd: unknown) => void) | null>(null);

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
      // Safe, payload-free client error signal via the official rtai.clientDiagnostic
      // command path. The send function is supplied by SendCommandBridge (rendered
      // inside AssistantRuntimeProvider) into sendCommandRef, because this initializer
      // runs outside the provider context where the hook cannot be called. kind only;
      // no error message is transmitted. Best-effort: no-op if the bridge has not yet
      // populated the ref.
      try {
        sendCommandRef.current?.(
          {
            type: "rtai.clientDiagnostic",
            event: "client_error",
            kind: "transport",
          }
        );
      } catch {
        /* diagnostics are best-effort */
      }
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
      <SendCommandBridge sendCommandRef={sendCommandRef} />
      <TransportReadyGate>
        <SessionIdStorageSync />
        {children}
      </TransportReadyGate>
    </AssistantRuntimeProvider>
  );
}

export function RtaiRuntimeProvider({ children }: { children: ReactNode }) {
  const [sessionEpoch, setSessionEpoch] = useState(0);
  // Deliberate session replacement (New Chat / cwd change) funnels through this
  // single choke point. The stored per-tab sessionId is cleared BEFORE the epoch
  // bump so the remounted runtime hydrates no stale id. Callers (Sidebar) close
  // the old backend session via DELETE /assistant/sessions/{id} first and only
  // reset on success; on close failure they surface the error WITHOUT resetting,
  // so a failed/racing close can never silently reuse a closing id — the
  // backend's closing-tombstone pre-stream 409 guard stays the second defense.
  const resetSession = useCallback(() => {
    clearStoredSessionId();
    setSessionEpoch((e) => e + 1);
  }, []);

  return (
    <SessionLifecycleContext.Provider value={{ resetSession }}>
      <RtaiAssistantRuntime key={sessionEpoch}>{children}</RtaiAssistantRuntime>
    </SessionLifecycleContext.Provider>
  );
}
