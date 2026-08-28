from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .agents.factory import AgentAdapterFactory, create_default_factory
from .api.routes import router

BASE_DIR = Path(__file__).resolve().parent


def create_app(
    adapter_factory: AgentAdapterFactory | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    ``adapter_factory`` exists for dependency injection in tests; production
    defaults to the OpenCode ACP adapter factory.
    """
    app = FastAPI(title="RTAI")
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
                " <code>frontendn/</code> directory. The vite build"
                " target is configured to output directly there,"
                " so no manual copy step is needed.</p>"
                "</body></html>"
            )
            return HTMLResponse(content=body, media_type="text/html", status_code=404)

    return app


app = create_app()
