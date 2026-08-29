// Phase 0 measurement probe — TEMPORARY, delete after the bundle measurement.
//
// Imports the exact assistant-ui primitives the part-model work intends to use
// and forces them to survive tree-shaking, so the CI build reports their real
// cost instead of an optimistic zero. Verified against
// @assistant-ui/react@0.15.17 `dist/index.d.ts` export block.
import {
  AssistantRuntimeProvider,
  ChainOfThoughtPrimitive,
  ComposerPrimitive,
  MessagePartPrimitive,
  MessagePrimitive,
  useExternalStoreRuntime,
} from "@assistant-ui/react";

export const assistantUiProbe = {
  AssistantRuntimeProvider,
  ChainOfThoughtPrimitive,
  ComposerPrimitive,
  MessagePartPrimitive,
  MessagePrimitive,
  useExternalStoreRuntime,
};

export type AssistantUiProbe = typeof assistantUiProbe;
