"""OpenCode over ACP.

Behaviour lives in :mod:`app.agents.acp`; this module supplies only what is
OpenCode-specific - where to find the binary, which environment variable
overrides it, and the OpenCode-specific model reassert that the vendor-neutral
generic ACP session must NOT contain (see AGENTS.md: agent-specific code lives
only here). Everything else (permissions, tool events, capability discovery,
selection, process ownership) is inherited.

Adding another ACP agent means writing a file of roughly this size.
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Any

from ...core.protocol import jsonable_model
from ...diagnostics import EVENT
from ...logging_config import log_event, short_id
from ..prompt_content import PromptContent
from .acp import AcpSession

logger = logging.getLogger(__name__)


class OpenCodeSession(AcpSession):
    """Adapter around the official ACP Python SDK for one OpenCode child.

    The child process spawned here is the ONLY OpenCode process this class
    ever touches; its handle is retained in an :class:`OwnedProcess` so
    cleanup stays scoped to what RTAi created (ADR-0006).
    """

    default_agent_name = "opencode"
    extra_args = ("acp",)

    def resolve_executable(self) -> str:
        """Locate the OpenCode binary, honouring the ``OPENCODE_BIN`` override."""
        executable = os.environ.get("OPENCODE_BIN") or shutil.which("opencode")
        if not executable:
            raise RuntimeError("OpenCode was not found in PATH (expected 'opencode')")
        return executable

    async def _reassert_selected_model(self) -> None:
        """Re-apply the user's selected model to the live OpenCode session.

        OpenCode requires the model config option to be reasserted immediately
        before each prompt; its ACP session does not otherwise guarantee the
        selected model is applied. This is OpenCode-specific behaviour and lives
        ONLY here - never in the vendor-neutral generic ACP session. It uses the
        single authorized ``set_config_option`` path that ``select()`` uses, with
        no fake model field in the ACP PromptRequest.
        """
        if not self._connection or not self._session_id:
            return
        caps = self._capabilities
        if not caps.selected_model or not caps.model_config_id:
            return
        self._record_diag(EVENT["ACP_CONFIG_OPTION_SENT"], "info", config_id=caps.model_config_id)
        try:
            result = await self._connection.set_config_option(
                session_id=self._session_id,
                config_id=caps.model_config_id,
                value=caps.selected_model,
            )
            dumped = jsonable_model(result)
            if isinstance(dumped, dict):
                options = dumped.get("configOptions")
                if isinstance(options, list):
                    caps.ingest_config_options(options)
            log_event(
                logger,
                logging.DEBUG,
                "acp_model_reasserted",
                session=short_id(self._session_id),
                model=caps.selected_model,
            )
            self._record_diag(
                EVENT["ACP_CONFIG_OPTION_CONFIRMED"], "info", config_id=caps.model_config_id
            )
        except Exception as exc:
            self._record_diag(
                EVENT["ACP_CONFIG_OPTION_FAILED"], "error", config_id=caps.model_config_id
            )
            log_event(
                logger,
                logging.WARNING,
                "acp_model_reassert_failed",
                session=short_id(self._session_id),
                error=str(exc),
            )

    async def submit_prompt(self, text: str) -> None:
        # OpenCode-specific: reassert the selected model through the authorized
        # set_config_option path immediately before the prompt. Generic ACP
        # adapters rely on select() alone; only OpenCode needs this reassert.
        await self._reassert_selected_model()
        return await super().submit_prompt(text)

    async def submit_prompt_content(self, content: list[PromptContent]) -> None:
        # Same OpenCode-specific reassert, applied to the multi-block prompt path.
        await self._reassert_selected_model()
        return await super().submit_prompt_content(content)


__all__ = ["OpenCodeSession", "OpenCodeAcpAdapter"]

OpenCodeAcpAdapter = OpenCodeSession
