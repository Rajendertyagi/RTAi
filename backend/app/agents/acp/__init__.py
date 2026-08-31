"""Shared Agent Client Protocol core.

This package holds everything that is true of the ACP specification rather
than of any one agent: session lifecycle, permission prompts with full tool
detail, tool-call event mapping, capability discovery from live config
options, and selection.

An adapter for a concrete agent subclasses :class:`AcpSession` and supplies
only how to locate its executable. See ``session.AcpSession`` for the contract
and ``opencode_acp.py`` for a worked example.
"""

from .mapping import (
    TERMINAL_STATUSES,
    TOOL_STATUS_MAP,
    map_tool_content,
    map_tool_locations,
    map_tool_status,
    permission_option,
    permission_tool_details,
    tool_call_id_of,
)
from .session import AcpSession

__all__ = [
    "TERMINAL_STATUSES",
    "TOOL_STATUS_MAP",
    "AcpSession",
    "map_tool_content",
    "map_tool_locations",
    "map_tool_status",
    "permission_option",
    "permission_tool_details",
    "tool_call_id_of",
]
