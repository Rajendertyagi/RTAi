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

> **Legacy note:** until Phase 2 lands, the backend WebSocket also accepts the
> old Deep Chat `{messages:[...]}` payload format and bare `{type:"cancel"}`.
> That format is **legacy and unchanged** by this document; the normalized
> commands below are the Phase-2 target and already spoken by MockTransport.

## Correlation rules

1. `session_id` is required on session-specific events (selections, turns,
   tool activity, permissions). Frames naming a different session than the
   active one must not mutate UI state.
2. `turn_id` is required on all prompt/generation events. Response-window
   events (`delta`, `done`, `tool_*`, `cancelled`) apply only when their turn
   matches the active turn.
3. `message_id` is required on user and assistant messages.
4. Streaming events carry an increasing `sequence`; deltas with a sequence ≤
   the last applied one are duplicates and must not append text.
5. Events for queued-but-not-active turns never update the visible response.
6. Selection state changes come **only** from authoritative selected-state
   events (`*_selected`); `command_result` acknowledgements never mutate
   selections.
7. Currently `session_id` equals the UI's in-memory session id. Phase 2 may
   introduce server-assigned ids via a future additive event.

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

### tool_start

| | |
|---|---|
| Direction | backend → ui |
| Required | `session_id`, `turn_id`, `tool_call_id`, `title` |
| Optional | `kind`, `status`, `content`, envelope extras |

```json
{"protocol_version": 1, "type": "tool_start",
 "session_id": "s", "turn_id": "t",
 "tool_call_id": "tc1", "title": "read_file", "kind": "read"}
```

UI: timeline entry. Content is untrusted data — never rendered unescaped.

### tool_update

Required: `session_id`, `turn_id`, `tool_call_id`.
Optional: `title`, `status`, `content`, envelope extras.

```json
{"protocol_version": 1, "type": "tool_update",
 "session_id": "s", "turn_id": "t", "tool_call_id": "tc1",
 "status": "running", "content": {"path": "src/app.ts"}}
```

UI: live update of the matching entry. Turn-scoped correlation.

### tool_result

| | |
|---|---|
| Direction | backend → ui |
| Required | `session_id`, `turn_id`, `tool_call_id`, `status` (`success`\|`error`\|`cancelled`) |
| Optional | `content`, `error_message`, envelope extras |

```json
{"protocol_version": 1, "type": "tool_result",
 "session_id": "s", "turn_id": "t", "tool_call_id": "tc1",
 "status": "error", "error_message": "Permission denied"}
```

UI: close entry; cancelled renders distinctly; content treated as untrusted.

### permission_request

| | |
|---|---|
| Direction | backend → ui |
| Required | `session_id`, `turn_id`, `permission_request_id`, `tool_call_id`, `options`: `{id, label}` list (`description?` allowed) |
| Optional | envelope extras |

```json
{"protocol_version": 1, "type": "permission_request",
 "session_id": "s", "turn_id": "t",
 "permission_request_id": "perm-1", "tool_call_id": "tc1",
 "options": [{"id": "allow_once", "label": "Allow once"}]}
```

UI: dialog built from the provided options. Option ids are data, never
hard-coded in components.

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

UI: mark generation stopped for that turn; other queued turns unaffected.

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

Attachment references carry metadata only: `id`, `name`, `mime_type`,
`size_bytes`, optional `kind`. Local filesystem paths, binary data and object
URLs are forbidden anywhere in protocol events. Phase 1 attachments are
mock/local-only; real upload transport is future work.

Cancel identifies the exact session and turn; cancelling a non-active turn
yields a successful no-op acknowledgement.

---

# Testing notes

Contract tests live under `tests/frontend/` (never beside production files).
Coverage includes: version gating, session/turn isolation, message
correlation, ordered/duplicate deltas, unknown-event tolerance, raw typing,
capabilities, model-specific thinking levels, attachment metadata, tool
lifecycle, permission option flow, command success/failure, scoped errors,
and queued-prompt isolation.
