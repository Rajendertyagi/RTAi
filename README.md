# RTAI — Reusable AI Chat

A lightweight, reusable AI chat application: React/Vite frontend, FastAPI
backend, agents over the official ACP Python SDK. First agent backend:
OpenCode (`opencode acp`). The architecture is agent-neutral — OpenCode is one
adapter, not the core.

## Status

Phase 0 (repository foundation) complete — see `docs/ROADMAP.md`.
The React/Vite frontend is the only UI; the legacy Deep Chat POC has been
removed.

## Architecture in one line

```
React UI → Transport hook → WebSocket → FastAPI → AgentAdapter → ACP SDK → opencode acp
```

Details: `docs/ARCHITECTURE.md`.

## Requirements

- Python 3.14+ with `fastapi`, `uvicorn`, `agent-client-protocol`
- OpenCode installed and authenticated (`opencode` on PATH, or set `OPENCODE_BIN`)
- **No local Node.js required**: frontend build runs in GitHub Actions only —
  see `.github/workflows/ci.yml`. Install Node ≥ 22.12 only if you want to
  run the frontend toolchain yourself.

## Running from a source checkout (no local build)

A plain source checkout does **not** contain the compiled frontend — generated
assets live only in CI artifacts. To run without Node:

1. Open the latest successful CI run for your branch on GitHub Actions.
2. Download the **`rtai-web-package`** artifact and extract it to a runtime
   directory (e.g. `rtai-runtime/`).
3. From that directory:

   ```bash
   cd rtai-runtime/backend
   python -m pip install -r requirements.txt
   python run.py
   ```

4. Open <http://127.0.0.1:8090> — the packaged frontend is served at `/`.

If you start the backend from a source checkout that has no built frontend
(`backend/app/static/dist/` absent), `/` shows an explicit **"Frontend build is
missing"** diagnostic page instead of the app; `/api/*` and `/ws` still work.

The runtime package contains exactly what is needed to run: backend source,
requirements, `run.py`, and the pre-built frontend. It excludes tests, caches,
`.git`, and development tooling.

## Development

```bash
# backend checks
python -m unittest discover -s tests/backend -t . -v
python -m ruff check backend tests/backend --config backend/pyproject.toml
cd backend && python -m mypy app

# frontend (requires Node; runs in CI otherwise)
cd frontend && npm ci && npm run typecheck
```

Testing strategy: `docs/TESTING.md`.

## Repository map

```
backend/    FastAPI app, AgentAdapter + OpenCode ACP adapter, tests
frontend/   React+Vite+TypeScript chat app
docs/       architecture, event protocol, testing, roadmap, ADRs
tests/      Python unit tests, integration tests, Playwright E2E
.github/workflows/  CI (build, test, package) — no workflow commits to git
```

## Generated assets

`backend/app/static/dist/` is produced by the Vite build and is **not tracked
in Git**. CI builds it fresh each run and passes it to packaging and browser
tests via artifact upload/download. The `.gitignore` entry
`backend/app/static/dist/` prevents accidental commits.

CI artifact retention is intentional and different for the two artifacts:

- **`frontend-dist`** — retained **1 day**. It is an intermediate artifact
  consumed within the same workflow run (packaging and browser jobs download
  it), so it needs no longer lifetime.
- **`rtai-web-package`** — retained **14 days**. Users download this artifact
  for local execution, so it stays available for two weeks.

Do not raise the `frontend-dist` retention or shorten `rtai-web-package` to a
day; the difference exists to avoid wasting storage while keeping the runnable
package downloadable.

## Key documents

| Doc | Purpose |
|---|---|
| [ARCHITECTURE](docs/ARCHITECTURE.md) | layers, lifecycles, boundaries |
| [EVENT_PROTOCOL](docs/EVENT_PROTOCOL.md) | normalized WS event contract |
| [TESTING](docs/TESTING.md) | test layers & conventions |
| [ROADMAP](docs/ROADMAP.md) | phased plan with statuses |
| [adr/](docs/adr/) | decision records |
