# RTAI — Reusable AI Chat

A lightweight, reusable AI chat application: React/Vite frontend, FastAPI
backend, agents over the official ACP Python SDK. First agent backend:
OpenCode (`opencode acp`). The architecture is agent-neutral — OpenCode is one
adapter, not the core.

## Status

Phase 0 (repository foundation) complete — see `docs/ROADMAP.md`.
The legacy Deep Chat POC is preserved under `backend/app/static` and is
**temporary/legacy**; the React frontend UI replaces it.

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

The runtime package contains exactly what is needed to run: backend source,
requirements, `run.py`, and the pre-built frontend. It excludes tests, caches,
`.git`, and development tooling.

## Quick start (from source, with local Node)

```bash
# Build the frontend once (Node ≥ 22 required)
cd frontend && npm ci && npm run build
cd ..

# Start the server (port 8090 by default)
cd backend
python -m pip install -r requirements.txt
python run.py
```

Open <http://127.0.0.1:8090>, enter an existing project folder, click **Connect**.

## Development

```bash
# backend checks
python -m unittest discover -s tests/backend -t . -v
python -m ruff check backend tests/backend --config backend/pyproject.toml
cd backend && python -m mypy app

# frontend (requires Node)
cd frontend && npm ci && npm run typecheck
```

Full commands: `docs/DEVELOPMENT.md`. Testing strategy: `docs/TESTING.md`.

## Repository map

```
backend/    FastAPI app, AgentAdapter + OpenCode ACP adapter, tests
frontend/   React+Vite+TypeScript chat app
docs/       product, architecture, event protocol, UI spec, dev, testing, roadmap, ADRs
tests/      Python unit tests, integration tests, Playwright E2E
.github/workflows/  CI (build, test, package) — no workflow commits to git
```

## Generated assets

`backend/app/static/dist/` is produced by the Vite build and is **not tracked
in Git**. CI builds it fresh each run and passes it to packaging and browser
tests via artifact upload/download. The `.gitignore` entry
`backend/app/static/dist/` prevents accidental commits.

## Key documents

| Doc | Purpose |
|---|---|
| [PRODUCT](docs/PRODUCT.md) | problem, use cases, non-goals |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | layers, lifecycles, boundaries |
| [EVENT_PROTOCOL](docs/EVENT_PROTOCOL.md) | normalized WS event contract |
| [UI_SPEC](docs/UI_SPEC.md) | legacy Loquix UI structure (superseded by frontend) |
| [DEVELOPMENT](docs/DEVELOPMENT.md) | setup & commands (Windows/Linux) |
| [TESTING](docs/TESTING.md) | test layers & conventions |
| [ROADMAP](docs/ROADMAP.md) | phased plan with statuses |
| [adr/](docs/adr/) | decision records |
