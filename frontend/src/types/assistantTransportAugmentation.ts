/**
 * Official AssistantTransport augmentation for RTAI capability discovery/selection.
 *
 * Verified against pinned @assistant-ui/react 0.15.17 + @assistant-ui/core 0.3.16:
 * - Custom commands extend `Assistant.Commands` (the `UserCommands` union the
 *   runtime serializes into the `commands` array of the /assistant POST body).
 * - Capability state extends `Assistant.ExternalState` (surfaced to the UI via the
 *   `state` field of `useAssistantTransportState`).
 *
 * Augmentation target is `@assistant-ui/core` (confirmed in
 * `core/dist/types/augmentations.d.ts`). The pinned declaration is:
 *   type UserExternalState =
 *     keyof Assistant.ExternalState extends never
 *       ? Record<string, unknown>
 *       : Assistant.ExternalState[keyof Assistant.ExternalState];
 * i.e. `UserExternalState` is the *value type* of the declared key. A single key
 * whose value is the full external-state shape is therefore required so that
 * `useAssistantTransportState` selectors receive a directly-indexable object
 * (not a union of value types). `rtai` is that key; its value type is the full
 * `RtaiAssistantState`, which already declares every field read by the selectors
 * (sessionId, status, error, rtaiCapabilities, rtaiCapabilitiesPending, cwd, messages).
 *
 * Command identifiers are namespaced (`rtai.`) and validated strictly server-side;
 * the runtime only forwards exactly the typed shape. Selection values are exact
 * adapter IDs (never display labels).
 */
import "@assistant-ui/core";
import type { RtaiAssistantState } from "./rtaiAssistantState";

declare module "@assistant-ui/core" {
  namespace Assistant {
    interface Commands {
      rtaiRefreshCapabilities: { type: "rtai.refreshCapabilities" };
      rtaiSelectAgent: { type: "rtai.selectAgent"; value: string };
      rtaiSelectModel: { type: "rtai.selectModel"; value: string };
      rtaiSelectMode: { type: "rtai.selectMode"; value: string };
      rtaiSelectThinking: { type: "rtai.selectThinking"; value: string };
      rtaiClientDiagnostic: {
        type: "rtai.clientDiagnostic";
        event:
          | "gate_ready"
          | "capability_command_sent"
          | "model_command_sent"
          | "permission_post_initiated"
          | "client_error"
          | "tool_group_visibility";
        kind?:
          | "refresh"
          | "agent"
          | "model"
          | "mode"
          | "thinking"
          | "transport"
          | "permission";
        optionLength?: number;
        status?: "running" | "complete" | "incomplete" | "requires-action" | "none";
        open?: boolean;
        toolCount?: number;
      };
    }
    interface ExternalState {
      // Full RTAI external state. Every field actually exposed through the
      // converter and read through `useAssistantTransportState` lives here.
      rtai: RtaiAssistantState;
    }
  }
}
