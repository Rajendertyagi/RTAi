# Roadmap

Statuses: `planned` | `in progress` | `blocked` | `complete`

## Phase 0 — Repository foundation
| Feature | Status |
|---|---|
| backend/ + frontend/ + docs/ structure | complete |
| AgentAdapter interface (agents/base.py) | complete |
| Normalized event protocol documented | complete |
| Transport interface + Mock/WebSocket implementations (frontend) | complete |
| Tooling: ruff/mypy/vitest/eslint/prettier/vite | complete |
| Legacy Deep Chat POC removed (React/Vite frontend is the only UI) | complete |

## Phase 1 — Loquix UI with mock transport
| Feature | Status |
|---|---|
| App shell, chat panel, composer (Loquix) | complete |
| Session sidebar (in-memory) with search/rename/delete | complete |
| Control bar: project folder, connection status, theme, sidebar/diagnostics toggles | complete |
| Compact two-row composer: attachments (local mock), agent/model/mode/thinking in toolbar, send/stop, compact overflow | complete |
| Protocol additions: agents_available/agent_selected, set_thinking/thinking_selected (additive) | complete |
| Tool timeline + permission dialog (mock events) | complete |
| Diagnostics panel with bounded raw-event stream | complete |
| Mock scenario controls (9 simulations) | complete |
| Component tests | complete |

> Permanent constraint recorded in Phase 0 docs: OpenCode process ownership —
> only the app-spawned child may be managed; see docs/adr/0006 and AGENTS.md.
> Verified green: CI run 32892049869 (branch feature/loquix-mock-ui).
>
> Superseded: the Phase 1 Loquix UI and its mock transport were replaced by the
> React/Vite frontend (Tailwind, modularized chat UI) speaking Protocol v1 over
> the real WebSocket. The legacy Deep Chat POC was removed.

## Phase 2 — Real ACP streaming

### Phase 2A — modular adapter foundation

| Feature | Status |
|---|---|
| Capability domain models + snapshot contract (`capabilities.py`) | complete |
| Generic `AgentAdapter` ABC with selection extension points | complete |
| `OwnedProcess` safe lifecycle (cooperative-first, scoped force, idempotent) | complete |
| `AgentAdapterFactory` dependency injection wired into routes | complete |
| OpenCode adapter refactor retaining owned handle | complete |
| Fake-adapter backend tests (no OpenCode execution) | complete |
| Runtime capability discovery from live ACP config options + notifications | complete |
| OpenCode Server HTTP adapter (loopback, private port, OwnedProcess) | complete |
| Shared capability mapper + benchmark instrumentation (injectable clock) | complete |
| Explicit adapter selector (`RTAI_OPENCODE_ADAPTER`), strict validation | complete |
| Real OpenCode compatibility integration (credential-free, server + ACP) | complete |
| Single-runtime Loquix UI with Protocol v1 WebSocket | complete |
| Controlled live benchmark (credentialed, real model) | planned |

### Phase 2B — streaming, selection and permissions over Protocol v1 (in progress)
| Feature | Status |
|---|---|
| Normalized `prompt`/`cancel` wire format replaces Deep Chat payloads | complete |
| WebSocketTransport wired to FastAPI | complete |
| WebSocket contract tests + mock-agent tests | complete |
| Structured backend logging (privacy-safe event chain, `RTAI_LOG_LEVEL`) | complete |
| services/ session orchestration extracted from route handler | planned |
| Provider-neutral prompt content model (`acp/prompt_content.py`) | complete |
| ACP attachment negotiation from InitializeResponse promptCapabilities | complete |
| Protocol v1 `attachments_available` capability event | complete |
| Multi-block prompt dispatch via `submit_prompt_content` | complete |
| RTAI safety limits (5 MiB/item, 10 MiB total, 10 blocks) | complete |
| History redaction for attachment metadata | complete |
| OpenCode HTTP/server adapter attachment support | deferred — separate task |

## Phase 3 — Models, modes and diagnostics
| Feature | Status |
|---|---|
| Model/mode discovery via AgentAdapter | planned |
| Selectors in control bar | planned |
| Timing/usage in diagnostics | planned |

## Phase 4 — Tool calls and permissions
| Feature | Status |
|---|---|
| Tool timeline UI | complete |
| Live tool streaming (`tool_update`) with throttled append-only output | complete |
| Rich tool cards (kind icons, command, diff preview, locations, error boundary) | complete |
| Permission dialog returning real outcomes | complete |
| Permission card enriched with tool details (title/kind/raw_input/content/locations) | complete |
| Slash-command autocomplete (`commands_available`) | complete |
| Permission result contract tests | planned |

## Phase 5 — SQLite session history
| Feature | Status |
|---|---|
| Storage service behind interface (`history/` repository) | complete |
| SQLite schema + migrations (WAL, partial native-id index, event dedup) | complete |
| Persist normalized transcript events (sanitized allowlist, per-session ordinal) | complete |
| REST read APIs: `GET /api/sessions`, `/api/sessions/{id}`, `/api/sessions/{id}/events` | complete |
| Session capability state surfaced via `CapabilitySnapshot.sessions` | complete |
| Session sidebar backed by SQLite | planned |
| Resume session via AgentAdapter | planned |

> Phase 5 landed backend-only: persistent storage and REST read APIs. The
> frontend sidebar and native session resume remain planned; native continuation
> is deferred to a later phase.

## Phase 6 — Tauri desktop wrapper
| Feature | Status |
|---|---|
| Tauri shell around frontend build | planned |
| TauriIpcTransport implementation | planned |

## Phase 7 — Integration adapters
| Feature | Status |
|---|---|
| Mountable FastAPI sub-app for existing projects | planned |
| Streamlit iframe example | planned |

## Phase 8 — Production hardening
| Feature | Status |
|---|---|
| Playwright browser E2E | planned |
| Error/reconnect hardening, packaging | planned |
