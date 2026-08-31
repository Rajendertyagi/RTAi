# Testing

## Mandatory layout

Every test in this repository lives under the repository-level `tests/` tree —
never beside production code, and never in extra test folders under
`backend/`, `frontend/`, or feature directories. Production code stays only in
`backend/` and `frontend/src/`.

```text
tests/
├── backend/       # Python unit tests (unittest)
├── frontend/     # React/TypeScript unit tests (vitest)
├── integration/   # cross-component suites (backend+frontend contract, Phase 2+)
├── e2e/           # browser E2E (Playwright, Phase 8)
├── fixtures/      # shared static test data
└── mocks/         # shared fakes (fake adapters/transports, Phase 2+)
```

## Layers

| Layer | Tool | Location | Status |
|---|---|---|---|
| Python unit tests (protocol helpers) | unittest (stdlib) | `tests/backend/` | active |
| Backend lint / types | ruff, mypy | `backend/pyproject.toml` | configured |
| Frontend unit tests | vitest | `tests/frontend/` | planned |
| Real OpenCode compatibility (credential-free) | unittest + real binary | `tests/integration/` | active (CI on `windows-latest`) |
| Component tests | vitest + browser env | `tests/frontend/` | Phase 8 (logic covered by unit tests today) |
| WebSocket contract tests | pytest + FastAPI TestClient | `tests/integration/` | Phase 2B |
| Mock-agent tests | Fake AgentAdapter | `tests/mocks/` + `tests/integration/` | Phase 2B |
| Windows compatibility | CI on Windows runner + local scripts | – | ongoing |
| Browser E2E | Playwright | `tests/e2e/` | Phase 8 |

Frontend checks are executed by GitHub Actions (`.github/workflows/ci.yml`,
Node 22 LTS); no local Node installation is required.

## Conventions

- Python: stdlib `unittest`, run from the repository root with
  `python -m unittest discover -s tests/backend -t .`
  (`-t .` matters on safe-path Pythons; `tests/backend/__init__.py` bootstraps
  `backend/` onto `sys.path` so `app.*` imports resolve from anywhere).
- Backend lint covers the relocated tests too:
  `python -m ruff check backend tests/backend --config backend/pyproject.toml`.
- Frontend: one `*.test.ts` per module under `tests/frontend/`; vitest picks
  them up via `include` in `frontend/vite.config.ts`. Contract changes require
  updating `docs/EVENT_PROTOCOL.md`, `frontend/src/types/protocol.ts`, and the
  contract tests in the same change.

## Real OpenCode integration tests (`tests/integration/`)

Credential-free tests that launch the real OpenCode v1.18.21 binary and verify
the server and ACP adapters end-to-end.  They are **skipped** when no real
binary is available (the CI integration job downloads the pinned release, verifies
its SHA-256, and sets `OPENCODE_BIN`).

```bash
# Locally (skips automatically if no binary):
python -m unittest discover -s tests/integration -t . -v

# CI (GitHub Actions, windows-latest):
# The integration job handles download/verify/extract automatically.
```

Each test method launches a fresh `opencode serve` or `opencode acp` child and
tears it down in `asyncTearDown`.  The fake-failure and pure-logic tests in
`tests/backend/` remain valuable for edge cases that the real binary cannot
reliably reproduce (malformed SSE, auth failures, bind races, etc.).

## Smoke test (manual, real OpenCode)

1. **From packaged artifact** (no local Node needed):
   - Download the `rtai-web-package` artifact from a successful CI run.
   - Extract it and run `python run.py` inside the `backend/` directory.
   - Open http://127.0.0.1:8090.

2. **From source** — a source checkout has no built frontend, so `/` shows the
   "Frontend build is missing" diagnostic. To exercise the full UI from source,
   download the `rtai-web-package` artifact as above (or build the frontend
   yourself with Node and run `python run.py` in `backend/`).

In both cases: enter an existing project folder and click Connect, send a
prompt, expect a streamed reply and ACP events in the debug panel, click stop
mid-generation for clean cancel.
