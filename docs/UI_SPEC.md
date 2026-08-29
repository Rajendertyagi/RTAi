# UI Specification

**Phase 1 status**: implemented against MockTransport on branch
`feature/loquix-mock-ui`. Components live in `frontend/src/components/`; state
flows through the normalized event reducer (`frontend/src/state/reducer.ts`).
Everything below describes the contract that implementation follows; deviations
are listed at the bottom.

## Application shell

Header (app title, connection badge) + session sidebar + main chat column +
collapsible diagnostics panel at the bottom/right.

## Session sidebar

List of past/active sessions; "New session" button; project-folder label per
entry. Populated from local state in Phase 1, SQLite in Phase 5.

## Chat panel

Message list (user/assistant bubbles, markdown, streaming cursor) + composer
(auto-grow textarea, Enter=send, Shift+Enter=newline).

## Control bar

Above the composer: model selector, mode selector, stop button (visible only
while generating), connection status.

## Model and mode selection

Dropdowns fed exclusively by `models_available` / `modes_available`. Never
hard-coded. Disabled with tooltip when the agent exposes none.

## Project-folder control

Text input + picker button shown before first connect; persisted in
localStorage; validated by backend (`status` error on failure).

## Message actions

Per assistant message: copy, regenerate (later phases). Per user message: edit
(later phase).

## Tool timeline

Cards per `tool_call_id`: title/kind from `tool_start`, live streaming content
from `tool_update` (throttled, append-only while running, highlighted once
final), final badge from `tool_result.status`. Kind drives the icon and
rendering: `execute`/bash shows the command + output, `edit` shows a line diff
preview, `read`/`search` shows paths + preview, `fetch` shows the URL, unknown
kinds fall back to a pretty-printed `raw_input`. Locations render relative to
the session `cwd`. Each card is isolated by an error boundary so one malformed
payload never breaks the message.

## Permission dialog

Inline card listing the requested tool + options from `permission_request`,
enriched with the tool's `title`/`kind`/`raw_input`/`content`/`locations` so
the user sees exactly what is being approved; resolves via `permission_response`;
Esc = safest option. Blocks the affected tool entry until `permission_result`.

## Diagnostics panel

Raw `raw` events, `timing`, `usage`, warnings; clear button; copy-to-clipboard.

## Responsive behaviour

≥1024px: sidebar + chat + diagnostics side by side.
640–1024px: sidebar collapses to drawer.
<640px: single column; diagnostics becomes full-screen sheet.

## Accessibility

- Full keyboard operability; visible focus rings.
- ARIA live region for streaming assistant text (polite).
- Permission dialog: focus trap, labelled by tool title.
- Contrast ≥ WCAG 2.1 AA in light and dark themes.

## States

| State | Trigger | UI |
|---|---|---|
| Empty | fresh session | Intro card with project-folder control |
| Loading | `status: starting` | Skeleton/spinner on connect controls |
| Streaming | deltas arriving | Cursor, stop button enabled |
| Disconnected | `status: disconnected` / socket close | Banner + reconnect action |
| Error | `error` event | Inline error bubble + diagnostics entry |

## Phase 1 implementation notes (deviations)

- Permission dialog uses a native `<dialog>` element styled with Loquix tokens
  (Loquix v0.4.1 ships no modal component).
- Tool-call "cancelled" state is rendered via the Loquix `error` status with a
  "Cancelled by user" label (Loquix `ToolCallStatus` has no cancelled value).
- Session persistence is in-memory only until Phase 5; the sidebar labels this.
- Message actions: assistant messages use `loquix-message-actions`
  (copy/regenerate/feedback); user messages use `loquix-action-edit` for
  edit-and-resend.
