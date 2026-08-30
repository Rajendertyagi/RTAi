from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .agents.factory import AgentAdapterFactory, create_default_factory
from .api.routes import router
from .history.repository import HistoryRepository
from .history.sqlite_repository import SqliteHistoryRepository

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR_ENV_KEY = "RTAI_DATA_DIR"
_DEFAULT_DATA_DIR = Path.home() / ".rtai"
_DB_FILENAME = "rtai.db"


def resolve_data_dir(environ: dict[str, str] | None = None) -> Path:
    """Return the storage root for chat history.

    ``RTAI_DATA_DIR`` wins when set; otherwise ``~/.rtai``. The directory is
    created lazily by the repository on first open, not here.
    """
    env = environ if environ is not None else os.environ
    raw = (env.get(DATA_DIR_ENV_KEY) or "").strip()
    if raw:
        return Path(raw).expanduser()
    return _DEFAULT_DATA_DIR


def create_app(
    adapter_factory: AgentAdapterFactory | None = None,
    history_repository: HistoryRepository | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    ``adapter_factory`` and ``history_repository`` exist for dependency
    injection in tests; production defaults to the OpenCode ACP adapter
    factory and a SQLite history repository under the data directory.
    """

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        repo = history_repository
        if repo is None:
            repo = SqliteHistoryRepository(resolve_data_dir() / _DB_FILENAME)
        _app.state.history_repository = repo
        try:
            yield
        finally:
            repo.close()

    app = FastAPI(title="RTAI", lifespan=lifespan)
    factory = adapter_factory if adapter_factory is not None else create_default_factory()
    app.state.adapter_factory = factory
    app.include_router(router)

    static_dist = BASE_DIR / "static" / "dist"
    if static_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dist), html=True), name="ui")
    else:
        # Diagnostic page registered as a catch-all; fires only when the
        # built frontend is absent.  Runs after API/WebSocket routes so
        # ``/api/*`` and ``/ws`` are never intercepted.
        @app.get("/{full_path:path}")
        async def _frontend_missing(full_path: str) -> HTMLResponse:
            body = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>RTAI -- Frontend missing</title></head><body>"
                "<h1>Frontend build is missing</h1>"
                "<p>Build the frontend and place the output into"
                " <code>backend/app/static/dist/</code>. Run"
                " <code>npm ci && npm run build</code> in the"
                " <code>frontend/</code> directory. The vite build"
                " target is configured to output directly there,"
                " so no manual copy step is needed.</p>"
                "</body></html>"
            )
            return HTMLResponse(content=body, media_type="text/html", status_code=404)

    return app


app = create_app()
