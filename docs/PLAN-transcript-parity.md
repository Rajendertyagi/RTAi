# RTAI transcript parity plan

Goal: make an agent reply read like a transcript — thinking, tool activity and
text appearing in the order they happened, with commands and outputs shown
properly — while keeping one shared core that any future ACP agent reuses.

Reference behaviour: OpenChamber's message rendering.
Status: draft, pending approval.
Branch: `feat/react-chat` only. Never merged to `main` during this work.

---

## 1. Why it looks wrong today

Three separate causes, all already confirmed by reading the code.

1. **A message is one text blob.** Every `delta` event concatenates into
   `message.text` (`ChatContext.tsx:242-252`), rendered as a single
   `ReactMarkdown` pass. `message.tools` is a side array rendered *after* all
   text (`MessageBubble.tsx:92-100`). A tool that ran second appears below text
   written tenth. Interleaving is impossible.

2. **Thinking is thrown away.** `core/protocol.py:49-55` only recognises
   `AgentMessageChunk`. ACP also sends `AgentThoughtChunk`
   (`acp/schema.py:4870`) — it arrives and is discarded.

3. **The tool card shows the wrong thing.** `commandFromRawInput`
   (`ToolCallCard.tsx:46-54`) looks for `rawInput.command`. OpenCode's bash tool
   sends `rawInput = { cwd: ... }`, so it finds nothing and falls back to a raw
   JSON dump. That is the `{ "cwd": "D:\\tmp" }` block currently on screen.

Polishing the card alone cannot fix (1) or (2). The message model has to change.

---

## 2. Architecture

Four pieces. The first two are backend and identical whichever way the frontend
goes.

### 2.1 Shared ACP core (backend)

Move everything that is true for *any* ACP agent out of `OpenCodeSession` (which
currently mixes process spawning with protocol translation) into a new
`backend/app/agents/acp/` package. ACP is a published spec, so this code is
stable and reusable:

- `session_update` routing: `AgentMessageChunk` → text, `AgentThoughtChunk` →
  thinking, `ToolCallStart` / `ToolCallProgress` → tool activity
- `request_permission` with full tool detail
- tool status / content / location mapping (already written, currently inline)

`opencode_acp.py` then shrinks to what is actually OpenCode-specific: the
executable and its arguments.

**Payoff:** a future ACP agent is a small file inheriting permission dialogs,
thinking blocks, tool cards, diffs, streaming and highlighting, with zero
frontend changes.

### 2.2 Part events on the wire

Backend emits `part_start` / `part_delta` / `part_done` carrying a part id and
type (`text` | `reasoning` | `tool`). The part id comes free from the spec:
`ContentChunk.messageId` (`acp/schema.py:4273`) is shared by every chunk of one
message, so no guessing or provider-specific hacks.

### 2.3 assistant-ui (frontend, unstyled primitives only)

Chosen because it solves the two things that ruled out AI Elements:

| | AI Elements | assistant-ui |
|---|---|---|
| Styling | Requires Tailwind + shadcn/ui (RTAI has neither) | Unstyled primitives — use RTAI's existing CSS |
| Backend | Their protocol | `ExternalStoreRuntime` — we keep our own |
| Part model | Partial | First-class `text` / `tool-call` / `data-*` parts |
| React 18 | — | Supported (`peerDependencies: ^18 \|\| ^19`) |

What it gives us: streaming state, auto-scroll, keyboard shortcuts,
accessibility, tool-result matching by `toolCallId`, and `ChainOfThought` (a
collapsible accordion for thinking steps and tool calls).

**Do NOT use `@assistant-ui/react-opencode`.** It makes the browser talk to
OpenCode directly, bypassing RTAI's backend and undoing the shared ACP core.

### 2.4 Our own card renderers

**Neither library provides a tool-call card or a diff viewer.** The bash card
showing the command and its highlighted output — the thing currently on screen —
must be written by us either way. Same for the diff. We write these against
OpenChamber's patterns, in RTAI's existing CSS.

---

## 3. Known assistant-ui limitations (accepted)

- **Pre-1.0** (0.15.17). Breaking changes are possible. MIT licensed, so no
  lock-in.
- **Streaming status is per message, not per part.** OpenChamber tracks
  `time.start` / `time.end` per part. We keep per-part timing in our own state
  and use assistant-ui purely for rendering, so this does not block us.
- **Reasoning is not a first-class part.** Carried as a `data-*` part.
- **Dependency weight.** 10 runtime deps, ~2.1 MB unpacked / 1144 files. This is
  why Phase 0 exists.

---

## 4. Phases

Each phase ends with a GitHub build and a report back. Nothing is merged to
`main`.

### Phase 0 — Measure assistant-ui (decision gate)

Add `@assistant-ui/react`, import only the primitives we intend to use, build in
CI, and measure the real bundle delta.

- **Files:** `frontend/package.json`, a throwaway probe component.
- **Outcome:** a number. Main bundle before/after and new chunk sizes.
- **Gate:** if the delta is acceptable, proceed. If not, Phases 1-3 are
  unchanged and Phase 4 falls back to hand-rolled renderers with no
  assistant-ui. Backend work is identical either way.
- **Visible change:** none. Build metrics only.

### Phase 1 — Shared ACP core (backend refactor)

- **Files:** new `backend/app/agents/acp/` package; `opencode_acp.py` reduced to
  a thin spawn config.
- **Outcome:** one place where ACP is translated; OpenCode is ~40 lines of
  spawn config.
- **Visible change:** none. Deliberately behaviour-preserving.

### Phase 2 — Part events and thinking (backend)

- **Files:** `acp/` core, `core/protocol.py`, `protocol.ts`.
- **Outcome:** `part_start` / `part_delta` / `part_done` on the wire;
  `AgentThoughtChunk` handled instead of discarded.
- **Visible change:** thinking blocks start appearing.

### Phase 3 — Frontend part model

- **Files:** `ChatContext.tsx` (reducer stores parts in order),
  `MessageBubble.tsx` (part dispatcher), new `ThinkingBlock.tsx`.
- **Outcome:** a message renders as an ordered list of parts.
- **Visible change:** thinking, tools and text interleave in true chronological
  order.

### Phase 4 — Tool card and diff

- **Files:** `ToolCallCard.tsx` rewritten, `PermissionCard.tsx` matching,
  `DiffPreview.tsx` refined, `chat.css`.
- **Outcome:** bash shows the command and its highlighted output; edits show a
  diff; the raw JSON dump is gone.
- **Visible change:** the main thing currently wrong on screen.

### Phase 5 — Polish and verification

- Per-part streaming without flashing, height caps on all untrusted content,
  final GitHub build, restart and verify on `http://127.0.0.1:8090`.

---

## 5. Out of scope

Stated now so it is not mistaken for an oversight:

- JSON tree viewers, subtask grouping, apply-patch buttons, file-reference
  chips, virtualised code blocks, multi-language UI text.
- assistant-ui's **styled "elements" layer** — we use unstyled primitives only,
  so RTAI keeps one styling system.
- assistant-ui's **cloud** features. RTAI is local-first (ADR-0005).
- Replacing RTAI's backend protocol with assistant-ui's. We keep ours and
  convert at the boundary.
- Tests. Deferred to the existing stabilisation phase, as originally scoped.
  Flagged below as a recommendation to revisit.

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| assistant-ui breaking change (pre-1.0) | Primitives are the stable Radix-style layer; MIT so no lock-in; pin exact version |
| Bundle growth | Phase 0 measures it before we commit |
| Per-part streaming not native | Keep timing in our own state; use assistant-ui for rendering only |
| Tool card and diff still ours | Phase 4 is explicitly hand-written, budgeted as such |
| Silent visual regressions | User reviews after every phase; nothing is claimed working unseen |

---

## 7. How each phase is verified

- GitHub Actions runs install, typecheck and build. Local frontend builds are
  not run (per established workflow).
- The generated build is pulled, the confirmed RTAI process on port 8090 is
  restarted, and the hashed assets are checked for HTTP 200.
- **Visual confirmation is the user's**, not mine. There is no browser
  automation in this environment. Each phase report states plainly what was
  verified mechanically and what was not.

Port 8080 is never touched.

---

## 8. Recommendation to revisit

Tests are deferred per the original scoping. Because the user cannot inspect
code personally, a thin test suite over the ACP translation layer would protect
against silent breakage more than it would for a developer. Worth considering
bringing this earlier than the stabilisation phase. `pytest` is already
configured (`pyproject.toml:36-38`).
