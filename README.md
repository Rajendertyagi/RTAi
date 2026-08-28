# RTAI — Reusable AI Chat

A lightweight, reusable AI chat application: React/Vite frontend, FastAPI
backend, agents over the official ACP Python SDK. First agent backend:
OpenCode (`opencode acp`). The architecture is agent-neutral — OpenCode is one
adapter, not the core.

## Status

Phase 0 (repository foundation) complete — see `docs/ROADMAP.md`.
The legacy Deep Chat POC is preserved under `backend/app/static` and is
**temporary/legacy**; the React frontendn UI replaces it.

## Architecture in one line

```
React UI → Transport hook → WebSocket → FastAPI → AgentAdapter → ACP SDK → opencode acp
```

Details: `docs/ARCHITECTURE.md`.

## Requirements

- Python 3.14+ with `fastapi`, `uvicorn`, `agent-client-protocol`
- OpenCode installed and authenticated (`opencode` on PATH, or set `OPENCODE_BIN`)
- **No local Node.js required**: frontend validation (format, lint, type-check,
  tests, build) runs in GitHub Actions — see `.github/workflows/ci.yml`.
  Install Node ≥ 22.12 only if you want to run the frontend toolchain yourself.

## Quick start (legacy POC — works today)

```bash
cd backend
python -m pip install -r requirements.txt
python run.py
```

Open <http://127.0.0.1:5000>, enter an existing project folder, click **Connect**.
The POC cancels every tool-permission request by design (safety).

PowerShell alternative from repo root: `scripts/dev.ps1`.

## Development

```bash
# backend checks
cd backend && python -m unittest discover -s tests -t . -v

# frontend (requires Node)
cd frontendn && npm install && npm run dev
```

Full commands: `docs/DEVELOPMENT.md`. Testing strategy: `docs/TESTING.md`.

## Repository map

```
backend/    FastAPI app, AgentAdapter + OpenCode ACP adapter, tests
frontendn/   React+Vite+TypeScript chat app
docs/       product, architecture, event protocol, UI spec, dev, testing, roadmap, ADRs
scripts/    cross-platform dev/test helpers
```

## Key documents

| Doc | Purpose |
|---|---|
| [PRODUCT](docs/PRODUCT.md) | problem, use cases, non-goals |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | layers, lifecycles, boundaries |
| [EVENT_PROTOCOL](docs/EVENT_PROTOCOL.md) | normalized WS event contract |
| [UI_SPEC](docs/UI_SPEC.md) | legacy Loquix UI structure (superseded by frontendn) |
| [DEVELOPMENT](docs/DEVELOPMENT.md) | setup & commands (Windows/Linux) |
| [TESTING](docs/TESTING.md) | test layers & conventions |
| [ROADMAP](docs/ROADMAP.md) | phased plan with statuses |
| [adr/](docs/adr/) | decision records |
