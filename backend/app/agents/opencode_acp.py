"""OpenCode over ACP.

Behaviour lives in :mod:`app.agents.acp`; this module supplies only what is
OpenCode-specific - where to find the binary and which environment variable
overrides it. Everything else (permissions, tool events, capability discovery,
selection, process ownership) is inherited.

Adding another ACP agent means writing a file of roughly this size.
"""

from __future__ import annotations

import os
import shutil

from .acp import AcpSession


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


__all__ = ["OpenCodeSession", "OpenCodeAcpAdapter"]

OpenCodeAcpAdapter = OpenCodeSession
