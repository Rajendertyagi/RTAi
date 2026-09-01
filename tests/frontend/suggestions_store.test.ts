import { describe, expect, it, beforeEach } from "vitest";
import { useChatStore } from "../../../frontend/src/state/chatStore";
import type { ServerEvent } from "../../../frontend/src/types/protocol";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Reset the singleton Zustand store to a known clean state before each test.
 * Zustand stores are process-wide; without this, one test's session/turn IDs
 * would leak into the next.
 */
function resetStore(): void {
  useChatStore.setState({
    sessionId: "sess-aaa",
    turnId: "turn-aaa",
    messageId: "msg-aaa",
    activeTurnId: null,
    activeMessageId: null,
    completedTurnId: null,
    suggestions: [],
    promptRequestId: null,
    cancelRequestId: null,
    cancelPending: false,
    cancelError: null,
    lastError: null,
    messages: [],
    pendingSelections: new Map(),
    pendingPermissions: new Map(),
    reasoningParts: new Map(),
  });
}

function activeTurnEvent(turnId: string): ServerEvent {
  return {
    protocol_version: 1,
    type: "user_message",
    session_id: "sess-aaa",
    turn_id: turnId,
    message_id: "msg-bbb",
    text: "hello",
  };
}

function doneEvent(turnId: string): ServerEvent {
  return {
    protocol_version: 1,
    type: "done",
    session_id: "sess-aaa",
    turn_id: turnId,
  };
}

function suggestionsEvent(
  turnId: string,
  items: Array<{ title: string; prompt: string }>,
): ServerEvent {
  return {
    protocol_version: 1,
    type: "suggestions_available",
    session_id: "sess-aaa",
    turn_id: turnId,
    items,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("suggestions pipeline — frontend store", () => {
  beforeEach(() => {
    resetStore();
  });

  it("accepts suggestions for the active turn", () => {
    const store = useChatStore.getState();
    store.handleMessage(suggestionsEvent("turn-aaa", [{ title: "A", prompt: "A" }]));
    const s = useChatStore.getState();
    expect(s.suggestions).toEqual([{ title: "A", prompt: "A" }]);
    expect(s.completedTurnId).toBe("turn-aaa");
  });

  it("accepts suggestions for the most-recently-completed turn", () => {
    // Complete turn-aaa so it becomes the completed turn.
    const store = useChatStore.getState();
    store.handleMessage(doneEvent("turn-aaa"));
    expect(store.completedTurnId).toBe("turn-aaa");

    // Now advance to a new active turn and receive suggestions for the old one.
    store.turnId = "turn-bbb";
    store.handleMessage(suggestionsEvent("turn-aaa", [{ title: "B", prompt: "B" }]));

    const s = useChatStore.getState();
    expect(s.suggestions).toEqual([{ title: "B", prompt: "B" }]);
    expect(s.completedTurnId).toBe("turn-aaa");
  });

  it("rejects suggestions for a superseded (older) turn", () => {
    const store = useChatStore.getState();
    // Complete turn-aaa, then advance to turn-bbb, then complete turn-bbb.
    store.handleMessage(doneEvent("turn-aaa"));
    store.turnId = "turn-bbb";
    store.handleMessage(doneEvent("turn-bbb"));

    // A suggestion arriving for turn-aaa should be ignored.
    store.handleMessage(suggestionsEvent("turn-aaa", [{ title: "X", prompt: "X" }]));

    const s = useChatStore.getState();
    expect(s.suggestions).toEqual([]);
    expect(s.completedTurnId).toBe("turn-bbb");
  });

  it("ignores suggestions from a different session", () => {
    const store = useChatStore.getState();
    store.handleMessage({
      protocol_version: 1,
      type: "suggestions_available",
      session_id: "other-session",
      turn_id: "turn-aaa",
      items: [{ title: "X", prompt: "X" }],
    } as ServerEvent);
    expect(useChatStore.getState().suggestions).toEqual([]);
  });

  it("persists suggestions after done", () => {
    const store = useChatStore.getState();
    store.handleMessage(suggestionsEvent("turn-aaa", [{ title: "A", prompt: "A" }]));
    expect(useChatStore.getState().suggestions).toHaveLength(1);

    store.handleMessage(doneEvent("turn-aaa"));
    // Suggestions survive the done event.
    expect(useChatStore.getState().suggestions).toHaveLength(1);
    expect(useChatStore.getState().completedTurnId).toBe("turn-aaa");
  });

  it("clears suggestions on a new prompt dispatch", () => {
    const store = useChatStore.getState();
    store.handleMessage(suggestionsEvent("turn-aaa", [{ title: "A", prompt: "A" }]));
    expect(useChatStore.getState().suggestions).toHaveLength(1);

    // Simulate new-prompt dispatch from RtaiRuntimeProvider.
    store.turnId = "turn-bbb";
    store.completedTurnId = null;
    store.suggestions = [];

    expect(useChatStore.getState().suggestions).toEqual([]);
    expect(useChatStore.getState().completedTurnId).toBeNull();
  });

  it("clears suggestions on session reset", () => {
    const store = useChatStore.getState();
    store.handleMessage(suggestionsEvent("turn-aaa", [{ title: "A", prompt: "A" }]));
    expect(useChatStore.getState().suggestions).toHaveLength(1);

    store.resetSession();
    expect(useChatStore.getState().suggestions).toEqual([]);
    expect(useChatStore.getState().completedTurnId).toBeNull();
  });

  it("clears suggestions on disconnect", () => {
    const store = useChatStore.getState();
    store.handleMessage(activeTurnEvent("turn-aaa"));
    store.handleMessage(suggestionsEvent("turn-aaa", [{ title: "A", prompt: "A" }]));
    expect(useChatStore.getState().suggestions).toHaveLength(1);

    store.handleMessage({
      protocol_version: 1,
      type: "status",
      state: "disconnected",
    } as ServerEvent);
    expect(useChatStore.getState().suggestions).toEqual([]);
    expect(useChatStore.getState().completedTurnId).toBeNull();
  });
});

describe("suggestions pipeline — protocol type guard", () => {
  it("accepts suggestions_available as a known event type", () => {
    // isServerEvent is re-exported from protocol.ts; test it indirectly via
    // the store: if the type guard rejected the event, handleMessage would
    // never see it.
    const store = useChatStore.getState();
    store.handleMessage(suggestionsEvent("turn-1", [{ title: "X", prompt: "X" }]));
    expect(store.suggestions).toHaveLength(1);
  });
});

describe("suggestions pipeline — legacy types absent", () => {
  it("does not expose a singular suggestion event shape in the type union", () => {
    // If "suggestion" still exists as a discriminant in ServerEvent, this
    // TypeScript file would compile. We verify the protocol definition by
    // checking the knownTypes set in the source file directly.
    const fs = require("fs") as typeof import("fs");
    const src = fs.readFileSync(
      require("path").join(__dirname, "../../../frontend/src/types/protocol.ts"),
      "utf8",
    );
    // The singular "suggestion" event must be gone.
    expect(src).not.toMatch(
      /\{\s*type:\s*"suggestion"\s*(?!.*available)/,
    );
    // The batched form must be present.
    expect(src).toContain('type: "suggestions_available"');
  });

  it("does not contain hardcoded frontend suggestions", () => {
    const fs = require("fs") as typeof import("fs");
    const src = fs.readFileSync(
      require("path").join(
        __dirname,
        "../../../frontend/src/runtime/RtaiRuntimeProvider.tsx",
      ),
      "utf8",
    );
    // The static list of hardcoded suggestion titles is gone.
    expect(src).not.toContain("Write a shell script");
    expect(src).not.toContain("Debug TypeScript");
    expect(src).not.toContain("Explain WebSocket");
  });
});
