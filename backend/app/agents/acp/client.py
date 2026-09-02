"""The generic ACP client handed to the SDK for every ACP session.

This is the bridge between the ACP SDK and an :class:`AcpSession`. It holds no
state of its own beyond a permission counter: everything is delegated to the
owning session, which owns the emit sink, the capability state and the pending
permission futures.

Nothing here is specific to any one agent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from ...core.protocol import jsonable_model
from ...logging_config import log_event, short_id
from .mapping import permission_option, permission_tool_details, tool_call_id_of

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .session import AcpSession

logger = logging.getLogger(__name__)


def create_client_class() -> type:
    """Build the ACP ``Client`` subclass, importing the SDK on demand.

    The import stays lazy so a missing ``agent-client-protocol`` surfaces as a
    clear RuntimeError from the adapter's ``start()`` rather than an ImportError
    the first time this package is imported.
    """
    from acp.interfaces import Client

    class AcpBrowserClient(Client):
        """Forwards ACP session updates and permission requests to the owner."""

        _perm_counter = 0

        def __init__(self, owner: AcpSession) -> None:
            self._owner = owner

        async def request_permission(
            self, session_id: str, tool_call: Any, options: list[Any], **kwargs: Any
        ) -> Any:
            owner = self._owner
            AcpBrowserClient._perm_counter += 1
            perm_id = f"perm-{AcpBrowserClient._perm_counter}"
            fut = asyncio.get_event_loop().create_future()
            owner._pending_permissions[perm_id] = fut

            try:
                await owner._send(
                    {
                        "type": "permission_request",
                        "permission_request_id": perm_id,
                        # Prefer the real ACP tool call id; if the SDK hands a
                        # tool_call without one, reuse the most recent tool call
                        # id the session announced (tool_start) so the permission
                        # correlates to that part instead of a duplicate card.
                        "tool_call_id": tool_call_id_of(
                            tool_call, owner._last_tool_call_id or f"tc-{perm_id}"
                        ),
                        # Skip protocol-invalid options (no official optionId)
                        # instead of inventing a positional or label-derived id.
                        "options": [
                            item
                            for item in (permission_option(o) for o in options)
                            if item is not None
                        ],
                        **permission_tool_details(tool_call),
                    }
                )
                log_event(
                    logger,
                    logging.INFO,
                    "acp_permission_request",
                    permission=short_id(perm_id),
                )
                option_id = await fut
                # ACP RequestPermissionResponse is a discriminated union:
                # selected + optionId, or cancelled. Anything else fails
                # pydantic validation on the agent side and reads as reject.
                return {"outcome": {"outcome": "selected", "optionId": option_id}}
            finally:
                owner._pending_permissions.pop(perm_id, None)

        async def session_update(
            self, session_id: str, update: Any, **kwargs: Any
        ) -> None:
            owner = self._owner
            log_event(
                logger,
                logging.DEBUG,
                "acp_session_update",
                event_type=type(update).__name__,
            )
            dumped = jsonable_model(update)
            await owner._send(
                {
                    "type": "raw",
                    "event": type(update).__name__,
                    "data": dumped,
                }
            )
            await owner._emit_content_part(update)
            owner._ingest_notification(dumped)
            await owner._emit_tool_event(dumped)
            if dumped.get("sessionUpdate") == "available_commands_update":
                await owner._emit_commands_available()

    return AcpBrowserClient


__all__ = ["create_client_class"]
