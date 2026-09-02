from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .agents.factory import AgentAdapterFactory, create_default_factory
from .api.health import router as health_router

BASE_DIR = Path(__file__).resolve().parent


def create_app(
    adapter_factory: AgentAdapterFactory | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    ``adapter_factory`` exists for dependency injection in tests; production
    defaults to the OpenCode ACP adapter factory.
    """

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Start idle session cleanup for AssistantTransport (local desktop,
        # conservative default 30m)
        try:
            from .transport.assistant.session_manager import (
                cleanup_all,
                start_idle_cleanup,
                stop_idle_cleanup,
            )

            await start_idle_cleanup()
        except Exception:
            pass
        try:
            yield
        finally:
            # Stop idle task and final cleanup
            try:
                from .transport.assistant.session_manager import cleanup_all, stop_idle_cleanup

                await stop_idle_cleanup()
            except Exception:
                pass
            # Application-shutdown cleanup for AssistantTransport adapters.
            try:
                from .transport.assistant.session_manager import cleanup_all

                await cleanup_all()
            except Exception:
                pass

    app = FastAPI(title="RTAI", lifespan=lifespan)
    factory = adapter_factory if adapter_factory is not None else create_default_factory()
    app.state.adapter_factory = factory
    app.include_router(health_router)
    # Sole active transport: the official assistant-stream HTTP transport at
    # ``POST /assistant``.  The legacy WebSocket/Protocol-v1 transport has been
    # removed; this app now exposes only the AssistantTransport API.
    try:
        from .transport.assistant.endpoint import router as assistant_router

        app.include_router(assistant_router)
    except Exception:
        pass

    static_dist = BASE_DIR / "static" / "dist"
    if static_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dist), html=True), name="ui")
    else:
        # Diagnostic page registered as a catch-all; fires only when the
        # built frontend is absent.  Runs after the API routes so ``/api/*``
        # and ``/assistant`` are never intercepted.
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
