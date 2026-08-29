"""RTAI server entry point.

Environment variables:
  RTAI_HOST  — loopback interface to bind (default: 127.0.0.1).
  RTAI_PORT  — port number; 0 requests the OS to pick an ephemeral port.
  RTAI_LOG_LEVEL — structured logging level (default: INFO).
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn
from app.agents.runtime_settings import resolve_from_environment
from app.logging_config import configure_logging, log_event
from app.main import create_app

logger = logging.getLogger("rtai.run")


def _resolve_host() -> str:
    raw = os.environ.get("RTAI_HOST", "127.0.0.1").strip()
    if not raw:
        return "127.0.0.1"
    return raw


def _resolve_port() -> int:
    raw = os.environ.get("RTAI_PORT", "8090").strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(f"RTAI_PORT must be an integer, got {raw!r}") from exc
    if port < 0 or port > 65535:
        raise ValueError(f"RTAI_PORT out of range (0-65535): {port}")
    return port


def _install_signal_handlers(server: uvicorn.Server) -> None:
    """Request a cooperative uvicorn shutdown on Ctrl-C / SIGTERM."""

    def _request_shutdown(signum: int, frame: object) -> None:
        log_event(logger, logging.INFO, "shutdown_requested", signal=signum)
        server.should_exit = True

    import contextlib
    import signal

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(ValueError, OSError, NotImplementedError):
            # Not in the main thread or unsupported on this platform.
            signal.signal(sig, _request_shutdown)


def main() -> None:
    level = configure_logging()
    log_event(logger, logging.INFO, "app_starting", log_level=level)
    host = _resolve_host()
    port = _resolve_port()
    kind = resolve_from_environment()
    log_event(logger, logging.INFO, "adapter_kind_selected", kind=kind)

    config = uvicorn.Config(
        create_app(),
        host=host,
        port=port,
        # Logging is configured above; uvicorn must not apply its own config
        # (which would override our handlers and duplicate records).
        log_config=None,
    )
    server = uvicorn.Server(config)
    _install_signal_handlers(server)

    # Run in a thread so we can print the URL after bind.
    import threading

    def _serve() -> None:
        asyncio.run(server.serve())

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()

    # Wait for the server to bind; uvicorn prints the URL once ready.
    import time

    timeout = 10
    start = time.monotonic()
    url = f"http://{host}:{port}"
    print(f"INFO: RTAI starting on {url}", flush=True)
    while time.monotonic() - start < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((host, port))
            log_event(logger, logging.INFO, "app_ready", url=url)
            print(f"INFO: RTAI ready at {url}", flush=True)
            break
        except OSError:
            time.sleep(0.2)
    else:
        log_event(
            logger,
            logging.WARNING,
            "app_ready_timeout",
            url=url,
            timeout_seconds=timeout,
        )
        print("WARN: RTAI did not bind within timeout; check logs", flush=True)

    thread.join()
    log_event(logger, logging.INFO, "shutdown_complete")


if __name__ == "__main__":
    main()
