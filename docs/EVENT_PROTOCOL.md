# RTAI Normalized Event Protocol

Version **1**. Every message exchanged over the WebSocket — both directions —
is a single JSON object carrying `protocol_version` and `type`, plus optional
correlation fields. The frontend mirror of these shapes lives in
`frontend/src/types/protocol.ts`.

## Envelope

```json
{
  "protocol_version": 1,
  "type": "delta",
  "session_id": "session-3",
  "turn_id": "turn-7",
  "message_id": "msg-12",
  "sequence": 4,
  "timestamp": 1735286400000
}
```

| Field | Req | Notes |
|---|---|---|
| `protocol_version` | always | `1`. Breaking changes bump the version. |
| `type` | always | Event name from the tables below. |
| `session_id` | optional | Owning logical session. |
| `turn_id` | optional | Prompt/generation turn. |
| `message_id` | optional | Concrete chat message. |
| `sequence` | optional | Monotonic counter for ordered streaming within a turn. |
| `timestamp` | optional | Sender clock, milliseconds since epoch. |

## Compatibility policy

- Within version 1: existing event names and their required fields are
  stable; new fields may be added as optional at any time.
- Any breaking change (renames, required-field changes, semantic breaks)
  requires version 2 and an agreed migration.
- Unknown event types must be ignored safely by the UI; they may be recorded
  in bounded diagnostics only.
- ACP/OpenCode-native structures may appear exclusively inside `raw` events.
- Frames whose `protocol_version` differs from 1 are recorded and ignored.
- TypeScript code uses `unknown` for opaque payloads — never `any`.

## Correlation rules

1. `session_id` is required on session-specific events (selections, turns,
   tool activity, permissions). Frames naming a different session than the
   active one must not mutate UI state.
2. `turn_id` is required on all prompt/generation events. Response-window
   events (`delta`, `done`, `tool_*`) apply only when their turn matches the
   active turn.
3. `message_id` is required on user and assistant messages.
4. Streaming events carry an increasing `sequence`; deltas with a sequence ≤
   the last applied one are duplicates and must not append text.
5. Events for queued-but-not-active turns never update the visible response.
6. Selection state changes come **only** from authoritative selected-state
   events (`*_selected`); `command_result` acknowledgements never mutate
   selections.
7. `command_result` correlation uses `request_id`; message storage and
   deduplication use `message_id`; turn streaming and cancellation use
   `turn_id`.

## Identifier contract

Every identifier has exactly one purpose and is never encoded inside another:

| Identifier | Meaning |
|---|---|
| `session_id` | Stable logical conversation identity. Unchanged across every turn in one chat; changes only when New Chat creates another conversation. |
| `turn_id` | Unique identity for one prompt execution. Generated before prompt dispatch so the turn can be cancelled before the first backend response. |
| `message_id` | Unique identity for one logical message. Never reused as a command `request_id`. |
| `request_id` | Unique correlation identity for one protocol command. Prompt and cancel commands receive different request IDs. |

Identifiers are UUIDs generated with `crypto.randomUUID()` in the frontend.
They are never built from `Date.now()` and turn/message identity is never
appended to `session_id`.

## Conversation session vs. server history id

The frontend owns the stable conversation `session_id` (one per chat, reused
for every turn). The backend independently assigns a server `rtai_session_id`
per WebSocket connection for history persistence (`GET /api/sessions/...`).
These are distinct identities with different owners:

- `session_id` — client-owned logical conversation identity, carried on the
  wire and used for UI correlation.
- `rtai_session_id` — backend-owned history identity, generated on accept,
  never derived from the client `session_id`, and used only for the SQLite
  transcript store.

The two are not interchangeable; the UI never sends `rtai_session_id` and the
backend never uses the client `session_id` as a history key.

## Agents

Agents are **logical agent profiles** (`id`, `label`, `description?`),
not operating-system processes:

- Selecting an agent does not attach to an existing OpenCode process.
- Agent selection never discovers or manages external processes.
- Process ownership remains exclusively inside the backend adapter
  (see docs/adr/0006).

## Model capabilities

`models_available` descriptors may carry optional capabilities:

```json
{
  "id": "mock-deep",
  "label": "Mock Deep",
  "capabilities": {
    "tools": true,
    "attachments": true,
    "vision": false,
    "thinking_levels": ["off", "low", "high"]
  }
}
```

All capability fields are optional for forward compatibility.

---

# Backend → UI events

### status — connection lifecycle

| | |
|---|---|
| Direction | backend → ui |
| Required | `type`, `state` (`starting`\|`ready`\|`disconnected`) |
| Optional | `cwd`, envelope fields |

```json
{"protocol_version": 1, "type": "status", "state": "ready"}
```

UI: show connection badge; composer enabled on `ready`.
Correlation: connection-wide; no session scoping.

### agent_info

| | |
|---|---|
| Direction | backend → ui |
| Required | `name` |
| Optional | `protocol_version`, envelope fields |

```json
{"protocol_version": 1, "type": "agent_info", "name": "opencode"}
```

UI: header display. Correlation: connection-wide.

### agents_available

| | |
|---|---|
| Direction | backend → ui |
| Required | `agents`: array of `{id, label}` (`description?` allowed) |
| Optional | envelope fields |

```json
{"protocol_version": 1, "type": "agents_available",
 "agents": [{"id": "mock-agent", "label": "Mock agent"}]}
```

UI: populate composer agent selector; first entry auto-selected when nothing
is chosen. Correlation: applies to the active session when `session_id`
matches; otherwise ignored.

### agent_selected

| | |
|---|---|
| Direction | backend → ui |
| Required | `session_id`, `agent_id` |
| Optional | remaining envelope fields |

```json
{"protocol_version": 1, "type": "agent_selected",
 "session_id": "session-3", "agent_id": "mock-agent"}
```

UI: authoritative selection update.

### models_available / model_selected

| | |
|---|---|
| Direction | backend → ui |
| Required | `models`: array of `{id, label}` (`capabilities?` allowed) / `model_id` |
| Optional | envelope fields |

```json
{"protocol_version": 1, "type": "models_available",
 "models": [{"id": "mock-fast", "label": "Mock Fast"}]}
{"protocol_version": 1, "type": "model_selected", "model_id": "mock-fast"}
```

UI: populate model selector; store capability metadata; selecting a model
re-derives available thinking levels when capabilities announce them.
Correlation: model_selected scoped to matching `session_id` when present.

### modes_available / mode_selected

Same shape as models with `modes` / `mode_id` and no capabilities.
Correlation as above.

### thinking_available

| | |
|---|---|
| Direction | backend → ui |
| Required | `thinking_levels`: subset of `off\|low\|medium\|high` |
| Optional | `model_id`, envelope fields |

```json
{"protocol_version": 1, "type": "thinking_available",
 "thinking_levels": ["off", "low"], "model_id": "mock-deep"}
```

UI: restrict the thinking selector to announced levels (∩ standard set).
Levels always originate here — components never assume all levels exist.

### thinking_selected

| | |
|---|---|
| Direction | backend → ui |
| Required | `level` (`off`\|`low`\|`medium`\|`high`) |
| Optional | `model_id`, envelope fields |

```json
{"protocol_version": 1, "type": "thinking_selected", "level": "medium"}
```

UI: authoritative reflection of reasoning effort.

### commands_available

| | |
|---|---|
| Direction | backend → ui |
| Required | `commands`: array of `{id, label}` (`description?`, `input_hint?` allowed) |
| Optional | `available` (`false` + `reason_code`/`reason_message` when the section is unavailable), envelope fields |

```json
{"protocol_version": 1, "type": "commands_available",
 "commands": [{"id": "web", "label": "web",
               "description": "Search the web for information",
               "input_hint": "query to search for"}]}
```

UI: populate the `/` slash-command autocomplete. Commands are invoked as
regular prompt text (`/name args`). The ACP adapter emits this event when the
runtime announces `available_commands_update` after session creation; the
server adapter announces commands during startup discovery. The list may be
re-emitted at any time when the runtime updates it.

### user_message

| | |
|---|---|
| Direction | backend → ui |
| Required | `session_id`, `turn_id`, `message_id`, `text` |
| Optional | envelope extras |

```json
{"protocol_version": 1, "type": "user_message",
 "session_id": "session-3", "turn_id": "turn-7",
 "message_id": "msg-12", "text": "Fix the failing test"}
```

UI: append user bubble; bind the response window to `turn_id`.
Correlation: opens the turn; mismatched sessions ignored.

### delta — assistant text chunk

| | |
|---|---|
| Direction | backend → ui |
| Required | `session_id`, `turn_id`, `sequence`, `text` |
| Optional | envelope extras |

```json
{"protocol_version": 1, "type": "delta",
 "session_id": "session-3", "turn_id": "turn-7",
 "sequence": 4, "text": "Looking at "}
```

UI: append into current assistant bubble.
Correlation: applied only for the active turn; `sequence` must exceed the
last applied value — duplicates and late frames are dropped (recorded in
diagnostics).

### done — assistant completion

| | |
|---|---|
| Direction | backend → ui |
| Required | `session_id`, `turn_id` |
| Optional | `reason` (`completed`\|`cancelled`\|`error`), envelope extras |

```json
{"protocol_version": 1, "type": "done",
 "session_id": "session-3", "turn_id": "turn-7", "reason": "completed"}
```

UI: finalize bubble, re-enable composer, cancel in-flight tool rows.
Correlation: turn-scoped.

`done` is the single terminal event for a turn. On cancellation the backend
emits exactly one `done` with `reason: "cancelled"`; it does not emit a
separate `cancelled` frame and does not emit a generic handler `error` after a
successful cancellation.

### tool_start

| | |
|---|---|
| Direction | backend → ui |
| Required | `session_id`, `turn_id`, `tool_call_id`, `title` |
| Optional | `kind`, `status`, `locations`, `raw_input`, envelope extras |

```json
{"protocol_version": 1, "type": "tool_start",
 "session_id": "s", "turn_id": "t",
 "tool_call_id": "tc1", "title": "read_file", "kind": "read",
 "locations": [{"path": "src/app.ts", "line": 42}],
 "raw_input": {"path": "src/app.ts"}}
```

UI: timeline entry. Content is untrusted data — never rendered unescaped.
`kind` is the ACP ToolKind / server tool name (drives icon and rendering);
`locations` are `{path, line?}` references; `raw_input` is the tool's input.

### tool_update

Required: `session_id`, `turn_id`, `tool_call_id`.
Optional: `status`, `content`, `locations`, envelope extras.

```json
{"protocol_version": 1, "type": "tool_update",
 "session_id": "s", "turn_id": "t", "tool_call_id": "tc1",
 "status": "running",
 "content": [{"type": "content", "text": "…streaming output…"}]}
```

UI: live update of the matching entry. `content` is a typed block array (see
below); while a tool runs the UI streams it and highlights it once final.
Turn-scoped correlation.

### tool_result

| | |
|---|---|
| Direction | backend → ui |
| Required | `session_id`, `turn_id`, `tool_call_id`, `status` (`success`\|`error`\|`cancelled`\|`aborted`\|`timeout`) |
| Optional | `content`, `locations`, `error_message`, envelope extras |

```json
{"protocol_version": 1, "type": "tool_result",
 "session_id": "s", "turn_id": "t", "tool_call_id": "tc1",
 "status": "error", "error_message": "Permission denied"}
```

UI: close entry; cancelled renders distinctly; content treated as untrusted.

### Tool content blocks

`content` on `tool_start`/`tool_update`/`tool_result`/`permission_request` is
an array of typed blocks mirroring the ACP discriminated union:

| `type` | Fields | Rendered as |
|---|---|---|
| `content` | `text?` | plain text (streamed live while running) |
| `diff` | `path`, `oldText?`, `newText` | line diff preview |
| `terminal` | `terminalId` | placeholder (no terminal widget yet) |

`locations` is an array of `{path, line?}`. Paths may be absolute; the UI
renders them relative to the session `cwd` when possible.

### permission_request

| | |
|---|---|
| Direction | backend → ui |
| Required | `session_id`, `turn_id`, `permission_request_id`, `tool_call_id`, `options`: `{id, label}` list (`description?`, `kind?` allowed) |
| Optional | `title`, `kind`, `raw_input`, `content`, `locations`, envelope extras |

```json
{"protocol_version": 1, "type": "permission_request",
 "session_id": "s", "turn_id": "t",
 "permission_request_id": "perm-1", "tool_call_id": "tc1",
 "title": "bash", "kind": "execute",
 "raw_input": {"command": "git status"},
 "options": [{"id": "allow_once", "label": "Allow once", "kind": "allow_once"}]}
```

UI: dialog built from the provided options, enriched with the additive tool
details (`title`/`kind`/`raw_input`/`content`/`locations`) so the user sees
exactly what is being approved. Option `kind` (when present) hints at the
nature of the choice — `allow_once`/`allow_always`/`reject_once`/
`reject_always` — and lets the UI auto-approve requests when the user enables
auto-accept. Option ids are data, never hard-coded in components.

### permission_result

Required: `session_id`, `turn_id`, `permission_request_id`.
Optional: `option_id`, envelope extras.

```json
{"protocol_version": 1, "type": "permission_result",
 "session_id": "s", "turn_id": "t",
 "permission_request_id": "perm-1", "option_id": "allow_once"}
```

UI: resolve dialog. Authoritative outcome echo.

### command_result

| | |
|---|---|
| Direction | backend → ui |
| Required | `request_id`, `command`, `success` |
| Optional | `code`, `message`, `effective_value`, envelope fields |

```json
{"protocol_version": 1, "type": "command_result",
 "request_id": "req-41", "command": "select_model", "success": false,
 "code": "unknown_model", "message": "Model not available"}
```

Emitted for: prompt, cancel, select_agent, select_model, select_mode,
set_thinking, permission_response. UI: bounded ack log only — failures are
surfaced without corrupting current selection; `*_selected` events remain the
authoritative state.

### usage / queue_state / timing

| | |
|---|---|
| Direction | backend → ui |
| Required | `pending` (queue_state) |
| Optional | everything else, envelope fields |

```json
{"protocol_version": 1, "type": "usage", "input_tokens": 120}
{"protocol_version": 1, "type": "queue_state", "pending": 1}
{"protocol_version": 1, "type": "timing", "total_ms": 512}
```

UI: subtle indicators/diagnostics panel only.

### cancelled

| | |
|---|---|
| Direction | backend → ui |
| Required | `session_id`, `turn_id` |
| Optional | envelope extras |

```json
{"protocol_version": 1, "type": "cancelled",
 "session_id": "s", "turn_id": "t"}
```

Legacy diagnostic frame. It is **not** the terminal event for a cancelled
turn. The terminal event for cancellation is `done` with
`reason: "cancelled"` (see below); the backend emits that `done` exactly once
and does not emit a separate `cancelled` frame for a cancelled turn.

### warning / error

warning Required: `message`. error Required: `message`;
error Optional: `code`, `recoverable`, `request_id`, plus correlation fields.

```json
{"protocol_version": 1, "type": "error",
 "message": "Model unavailable", "code": "model_unavailable",
 "recoverable": true, "turn_id": "turn-9"}
```

UI: non-blocking toast (warning) / inline error + diagnostics (error).
An error affects only its correlated command or turn; frames referencing a
different turn/session leave the visible response untouched.

### raw — debug passthrough

| | |
|---|---|
| Direction | backend → ui |
| Required | `event` (string), `data` (unknown) |
| Optional | envelope fields |

```json
{"protocol_version": 1, "type": "raw",
 "event": "AgentMessageChunk", "data": {"content": {"text": "Hi"}}}
```

The ONLY place ACP/OpenCode-native payloads may appear. Stored in a bounded
ring buffer (200 entries) shown in diagnostics.

---

# UI → backend commands

Every command carries `request_id` (unique, for `command_result`) plus the
envelope. All acknowledge via `command_result`; selected-state events remain
authoritative.

| Command | Required beyond envelope | Example payload core |
|---|---|---|
| `prompt` | `session_id`, `turn_id`, `message_id`, `text`, `attachments?` | see below |
| `cancel` | `session_id`, `turn_id` | identifies the exact turn to stop |
| `select_agent` | `session_id`, `agent_id` | logical profile switch |
| `select_model` | `session_id`, `model_id` | model switch |
| `select_mode` | `session_id`, `mode_id` | mode switch |
| `set_thinking` | `session_id`, `level` | one of the standard levels |
| `permission_response` | `session_id`, `turn_id`, `permission_request_id`, `option_id` | answers a request |

Every command carries a fresh `request_id` (unique, for `command_result`
correlation). A prompt and its later cancel are **different commands** and
therefore receive **different** `request_id` values. The cancel reuses the
target prompt's `session_id` and `turn_id` but never its `request_id`.

### prompt example

```json
{
  "protocol_version": 1,
  "request_id": "req-42",
  "type": "prompt",
  "session_id": "session-3",
  "turn_id": "turn-8",
  "message_id": "msg-15",
  "text": "Summarize the attached report",
  "attachments": [
    {"id": "att-1", "name": "report.pdf",
     "mime_type": "application/pdf", "size_bytes": 48213, "kind": "file"}
  ]
}
```

### prompt — text-only or multi-block

The `prompt` command accepts **either** a plain `text` string (legacy path)
**or** an ordered `prompt` array of content blocks. Both must not be present
simultaneously. When `prompt` is used, the `text` field is omitted.

```json
{
  "protocol_version": 1,
  "request_id": "req-42",
  "type": "prompt",
  "session_id": "session-3",
  "turn_id": "turn-8",
  "message_id": "msg-15",
  "prompt": [
    {"kind": "text",      "name": "message", "text": "Summarize this"},
    {"kind": "image",     "name": "diagram.png",
     "mime_type": "image/png", "data_base64": "..."},
    {"kind": "resource_link", "name": "report.pdf",
     "uri": "file:///project/report.pdf",
     "mime_type": "application/pdf"}
  ]
}
```

#### Block kinds

| `kind` | Required fields | Description |
|---|---|---|
| `text` | `name`, `text` | Plain text (always supported) |
| `image` | `name`, `mime_type`, `data_base64` | Base64-encoded image |
| `audio` | `name`, `mime_type`, `data_base64` | Base64-encoded audio |
| `resource_link` | `name`, `uri` | URI reference to external resource |
| `embedded_text` | `name`, `mime_type`, `text` | Inline text resource |
| `embedded_blob` | `name`, `mime_type`, `data_base64` | Inline binary resource |

#### Capability gating

Image, audio, and embedded resources are **not** guaranteed available. The
UI must check the `attachments_available` event emitted at connection time:

```json
{"type": "attachments_available", "available": true,
 "block_types": ["resource_link", "image"],
 "max_item_bytes": 5242880, "max_total_bytes": 10485760, "max_count": 10}
```

Blocks whose kind is not in `block_types` must not be sent. Text-only prompts
remain valid even when `attachments_available.available` is `false`.

#### Safety limits

RTAI enforces its own limits independently of the provider:

| Limit | Default | Config |
|---|---|---|
| Max bytes per attachment | 5 MiB | `RTAI_ATTACHMENT_MAX_ITEM_BYTES` |
| Max total bytes per prompt | 10 MiB | `RTAI_ATTACHMENT_MAX_TOTAL_BYTES` |
| Max block count per prompt | 10 | `RTAI_ATTACHMENT_MAX_COUNT` |

Violations return a normalized `command_result` with `success: false`.

#### Validation rules

- Unknown `kind` values are rejected.
- Mutually exclusive fields are enforced (e.g. `image` cannot have `text`).
- Base64 is strictly decoded; invalid encoding returns a client error.
- `file:` URIs must resolve inside the project root.
- `https:` URIs are allowed for remote resources.
- Credentials in URIs are rejected.
- Filename path traversal (`..`, `/`, `\`) is rejected.
- MIME types are treated as untrusted metadata; only `image/*` and `audio/*`
  prefixes are accepted for inline blocks.
- Raw attachment content is never persisted in history — only kind, name,
  MIME type, and decoded byte size are stored.

Cancel identifies the exact session and turn. The backend cancels only when
the cancel's `session_id` and `turn_id` match the active turn; a stale or
mismatched cancel (or a cancel with no turn in flight) is a safe idempotent
no-op that never cancels a newer/different turn. Every cancel command receives
one correlated `command_result` using its own `request_id`, and a successful
cancellation terminates with exactly one `done {reason: "cancelled"}`.

> **Limitation:** only one turn is active per WebSocket. A second prompt while
> another turn is active is rejected honestly with a failed `command_result`
> (`"A response is already running"`); it is never silently replaced or
> cancelled.

---

# Testing notes

Contract tests live under `tests/frontend/` (never beside production files).
Coverage includes: version gating, session/turn isolation, message
correlation, ordered/duplicate deltas, unknown-event tolerance, raw typing,
capabilities, model-specific thinking levels, attachment metadata, tool
lifecycle, permission option flow, command success/failure, scoped errors,
and queued-prompt isolation.
