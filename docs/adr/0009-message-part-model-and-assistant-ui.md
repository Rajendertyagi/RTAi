# ADR-0009: Message part model, shared ACP core and assistant-ui primitives

Status: proposed (2026-08-29)
Phase: 2B → 4

## Context

Agent replies render as a single markdown blob with tool cards appended after
it, so a transcript cannot show thinking, tool activity and text in the order
they happened. Three confirmed causes:

1. `ChatContext` concatenates every `delta` into one `message.text` string and
   `MessageBubble` renders `message.tools` after all text. Interleaving is
   structurally impossible.
2. `core/protocol.py` recognises only `AgentMessageChunk`. ACP also sends
   `AgentThoughtChunk` (`acp/schema.py:4870`), which is discarded.
3. The tool card's `commandFromRawInput` looks for `rawInput.command`;
   OpenCode's bash tool sends `rawInput = { cwd: ... }`, so it falls back to a
   raw JSON dump.

Separately, all ACP translation is inline in `OpenCodeSession`, so a second ACP
agent would mean duplicating and maintaining it.

Two component libraries were evaluated. **AI Elements** was rejected: it is
built on shadcn/ui and therefore Tailwind, and RTAI uses plain CSS with CSS
custom properties (no `tailwind.config`, no `postcss.config`, no
`components.json`). Adopting it would mean migrating the entire styling
approach and running two CSS systems. It also has no tool-call card and no
diff component.

## Decision

1. **Model a message as an ordered list of parts** (`text` | `reasoning` |
   `tool`) rather than a text blob plus a tools array. Part identity comes from
   the ACP spec: `ContentChunk.messageId` (`acp/schema.py:4273`) is shared by
   every chunk of one message.

2. **Extract a shared ACP core** into `backend/app/agents/acp/`, holding
   everything true for any ACP agent: `session_update` routing, permission
   requests with full tool detail, and tool status/content/location mapping.
   `opencode_acp.py` keeps only what is OpenCode-specific — the executable and
   arguments.

3. **Use `@assistant-ui/react` unstyled primitives only**, wired through
   `ExternalStoreRuntime` so RTAI keeps its own state, its own backend and its
   own protocol. Chosen because it requires no Tailwind and no backend
   replacement — the two blockers that eliminated AI Elements. The styled
   "elements" layer and all cloud features are excluded.

4. **Hand-write the tool-call card and diff viewer.** Neither library provides
   them, so these are ours either way, written against RTAI's existing CSS.

Explicitly rejected: `@assistant-ui/react-opencode`, which would make the
browser talk to OpenCode directly, bypassing RTAI's backend and undoing the
shared ACP core.

## Consequences

- A future ACP agent is a small file inheriting permissions, thinking blocks,
  tool cards, diffs, streaming and highlighting, with no frontend changes.
- Code follows the published ACP spec rather than one vendor's quirks, so it
  survives OpenCode updates.
- RTAI keeps one styling system and one state owner.
- Adds 10 runtime dependencies and ~2.1 MB unpacked. Phase 0 of the plan
  measures the real bundle delta before this is committed; if it is
  unacceptable, the backend phases are unaffected and only the renderer layer
  falls back to hand-written components.
- `@assistant-ui/react` is pre-1.0 (0.15.17). Mitigated by using only the
  unstyled primitives (the stable Radix-style layer), pinning the exact
  version, and the MIT licence (no lock-in).
- assistant-ui tracks streaming status per message, not per part. Per-part
  timing stays in RTAI's own state; assistant-ui is used for rendering only.

## Implementation plan

`docs/PLAN-transcript-parity.md`, phased: measure → shared core → part events →
frontend part model → tool card and diff → polish. Each phase ends with a
GitHub build and a report; nothing merges to `main`.
