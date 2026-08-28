"""Adapter factory boundary (dependency injection).

Routes and services obtain adapters exclusively through a factory, so tests
can inject fakes and future agent providers can be added without touching the
UI or transport layers. No global mutable singleton lives here.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from ..logging_config import log_event
from .base import AgentAdapter
from .opencode_acp import OpenCodeSession

logger = logging.getLogger(__name__)


@runtime_checkable
class AgentAdapterFactory(Protocol):
    def create(self) -> AgentAdapter:
        """Return one adapter instance for a single UI session."""
        ...


class OpenCodeAdapterFactory:
    """ACP factory: one OpenCode ACP session per created adapter."""

    def create(self) -> AgentAdapter:
        log_event(
            logger,
            logging.DEBUG,
            "adapter_created",
            factory=type(self).__name__,
        )
        return OpenCodeSession()


class ServerAdapterFactory:
    """OpenCode headless-server factory (candidate; benchmark pending)."""

    def create(self) -> AgentAdapter:
        from .opencode.server_adapter import OpenCodeServerAdapter

        log_event(
            logger,
            logging.DEBUG,
            "adapter_created",
            factory=type(self).__name__,
        )
        return OpenCodeServerAdapter()


def create_default_factory(environ: dict[str, str] | None = None) -> AgentAdapterFactory:
    """Factory chosen by the explicit RTAI_OPENCODE_ADAPTER setting.

    Unset resolves to the ACP factory, preserving prior behavior. Invalid
    values raise AdapterSelectionError - there is no silent fallback.
    """
    from .runtime_settings import resolve_from_environment

    kind = resolve_from_environment(environ)
    if kind == "opencode_server":
        return ServerAdapterFactory()
    return OpenCodeAdapterFactory()
