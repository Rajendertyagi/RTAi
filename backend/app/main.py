from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .agents.factory import AgentAdapterFactory, create_default_factory
from .api.health import router as health_router
from .diagnostics import AppSupervisor

BASE_DIR = Path(__file__).resolve().parent


def _registry_counts_safe() -> dict[str, int]:
    """Supervisor counts provider: the session manager's safe registry counts.

    Lazy + defensive on purpose (same pattern as the lifespan below): if the
    session manager stack cannot even be imported, the app supervisor and the
    diagnostics endpoints must keep working with empty counts instead of
    failing. Returns ints only — never ids, paths, or adapter internals.
    """
    try:
        from .transport.assistant.session_manager import registry_counts

        return registry_counts()
    except Exception:
        return {}


def create_app(
    adapter_factory: AgentAdapterFactory | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    ``adapter_factory`` exists for dependency injection in tests; production
    defaults to the OpenCode ACP adapter factory.
    """

    # One explicit app-level supervisor owned by THIS FastAPI lifespan. It owns
    # the app lifecycle status and the ONE global safe diagnostics hub, and
    # coordinates (never replaces) the existing session manager, which stays the
    # sole owner of the ACP/OpenCode child processes.
    supervisor = AppSupervisor(counts_provider=_registry_counts_safe)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Exact owner point: app starting. Recorded before anything else so the
        # Logs page can see the app even when session-manager startup fails.
        supervisor.record_starting()
        # Coordinate the existing session manager: start idle session cleanup
        # for AssistantTransport (local desktop, conservative default 30m).
        try:
            from .transport.assistant.session_manager import (
                cleanup_all,
                start_idle_cleanup,
                stop_idle_cleanup,
            )

            await start_idle_cleanup()
        except Exception:
            pass
        # Exact owner point: app ready. Recorded regardless of session-manager
        # startup success — /api/health and /api/diagnostics must work even when
        # chat/session startup fails.
        supervisor.record_ready()
        try:
            yield
        finally:
            # Exact owner point: app shutting down (before teardown begins).
            supervisor.record_shutting_down()
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
    # Expose the supervisor for the read-only GET /api/diagnostics endpoint
    # (same app.state dependency-injection pattern as ``adapter_factory``).
    app.state.supervisor = supervisor
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
