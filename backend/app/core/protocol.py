from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MCPServerConfig:
    """Configuration for an MCP server to attach to an ACP session.

    The ACP spec passes MCP server definitions at ``session/create`` time.
    RTAI owns the subprocess lifecycle here: the server is started by the
    factory and torn down when the adapter closes.
    """

    name: str
    command: str
    args: tuple[str, ...] = field(default_factory=tuple)
    env: dict[str, str] | None = None
    cwd: str | None = None


def resolve_project_path(value: str | None) -> Path:
    """Return an existing project directory or raise a clear ValueError.

    Blank / whitespace-only values are treated as "not provided".  In that
    case the caller should fall back to RTAI_PROJECT_ROOT if configured; this
    helper never does that implicitly because the fallback depends on the
    runtime environment, not on the wire value.
    """
    stripped = (value or "").strip()
    if not stripped:
        raise ValueError("project_folder_not_provided")
    candidate = Path(stripped).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"Project folder does not exist: {candidate}") from exc
    if not resolved.is_dir():
        raise ValueError(f"Project path is not a folder: {resolved}")
    return resolved


def extract_latest_user_text(payload: dict[str, Any]) -> str:
    """Extract the newest non-empty user message from a Protocol v1 prompt command."""
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Expected a 'text' field with non-empty user input")
    return text.strip()


def jsonable_model(value: Any) -> Any:
    """Convert ACP/Pydantic values into WebSocket-safe JSON data."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, dict):
        return {str(k): jsonable_model(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable_model(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def text_from_acp_update(update: Any) -> str | None:
    """Return text only for ACP agent-message chunks."""
    if type(update).__name__ != "AgentMessageChunk":
        return None
    content = getattr(update, "content", None)
    text = getattr(content, "text", None)
    return text if isinstance(text, str) else None


# ACP content chunk class name -> RTAI part type.
#
# ACP streams two kinds of content chunk and both carry text:
#   AgentMessageChunk - the reply the user is meant to read
#   AgentThoughtChunk - chain-of-thought ("thinking")
# Thinking was previously discarded everywhere because only the message
# chunk was ever recognised.
_ACP_CHUNK_KINDS = {
    "AgentMessageChunk": "text",
    "AgentThoughtChunk": "reasoning",
}


def acp_chunk_kind(update: Any) -> str | None:
    """Return the RTAI part type for an ACP content chunk, or None.

    Returning None means the update is not streamed content (a tool call, a
    mode change, a plan update...) and belongs to a different event path.
    """
    return _ACP_CHUNK_KINDS.get(type(update).__name__)


def text_from_acp_chunk(update: Any) -> str | None:
    """Text carried by any ACP content chunk, message or thought."""
    content = getattr(update, "content", None)
    text = getattr(content, "text", None)
    return text if isinstance(text, str) else None
