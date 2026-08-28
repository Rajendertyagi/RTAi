# AGENTS.md

Instructions for coding agents working in this repository.

## Before editing

1. Read `docs/ARCHITECTURE.md` and `docs/EVENT_PROTOCOL.md` first.
2. Check `docs/ROADMAP.md` for the current phase; do not pull future phases forward.

## Hard rules

- **Backend neutrality**: agent-specific code lives only in
  `backend/app/agents/opencode_acp.py`. Application code depends on
  `backend/app/agents/base.py` (`AgentAdapter`), never on the ACP SDK directly.
- **Never hard-code model or mode lists** anywhere in backend or frontend.
- **Keep UI separate from transport**: components import `Transport` from
  `frontendn/src/transport/transport.ts`; never instantiate WebSocket directly.
- Do not silently change protocol payloads. Any event change requires:
  update to `docs/EVENT_PROTOCOL.md` + `frontendn/src/types/protocol.ts` + tests,
  and only additive/optional fields unless a breaking change is agreed.
- **Add or update tests** for every behavioural change.
  Python: `python -m unittest discover -s tests/backend -t .` (repo root)
  Frontend: `cd frontendn && npm run test`.
- **Windows support is mandatory**: use `pathlib`, avoid POSIX-only process
  handling, keep the `sys.path` bootstrap in `backend/run.py` (safe-path Pythons).
- **OpenCode process ownership** (see docs/adr/0006): manage ONLY the exact
  OpenCode child process this app spawned; track its PID/handle and ACP session
  id. Never enumerate, attach to, or terminate unrelated OpenCode processes.
  Process-name-wide termination (`taskkill /IM`, `pkill opencode`) is
  prohibited. Never start, discover, or reuse a user's own OpenCode instance.
- **Runtime capability discovery**: production code must not hard-code agents,
  models, modes, thinking levels, tools, commands, permission option IDs,
  attachment or provider capabilities. Query them at runtime through the
  adapter; mock values live only in explicit tests/dev mode; when a capability
  is unavailable the UI disables it and says why. Capability models and the
  owned-process contract live in
  `backend/app/agents/{capabilities,owned_process}.py` (see docs/adr/0007).
- **Dual OpenCode adapters**: `OpenCodeServerAdapter` (official HTTP server,
  preferred benchmark candidate) and `OpenCodeAcpAdapter` (portable ACP v1)
  share one `CapabilitySnapshot` contract; the active kind comes from
  `RTAI_OPENCODE_ADAPTER` and invalid values fail at startup with no silent
  fallback (docs/adr/0008). Selection commands use only runtime-provided
  config ids - never assumed names.
- **Preserve unrelated user changes** — do not revert, reformat, or "clean up"
  files you were not asked to touch.

## Mandatory test organization

All tests live in the repository-level `tests/` tree:

```text
tests/
├── backend/
├── frontendn/
├── integration/
├── e2e/
├── fixtures/
└── mocks/
```

- Every new test goes inside `/tests`: Python units in `tests/backend/`,
  frontendn units in `tests/frontendn/`, cross-component suites in
  `tests/integration/`, browser E2E (Playwright) in `tests/e2e/`, shared
  static data in `tests/fixtures/`, shared fakes (fake adapters/transports)
  in `tests/mocks/`.
- Never place `*.test.ts`, `*.spec.ts`, `test_*.py`, fixtures, or mocks beside
  production files.
- Never create additional test folders under `backend/`, `frontendn/`, or any
  feature directory.
- Production code lives only under `backend/` and `frontendn/src/`.

## Process

- Update `docs/ROADMAP.md` status when a feature lands.
- Run lint/type checks before declaring done (see docs/DEVELOPMENT.md).
- Never commit secrets; `.env` is ignored — use `.env.example` as template.
