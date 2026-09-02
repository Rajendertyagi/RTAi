"""AssistantTransport package for RTAI.

This package exposes the official ``assistant-stream`` HTTP transport
at ``POST /assistant`` without copying the existing ACP adapter code.
"""

from .endpoint import router as assistant_router  # noqa: F401

__all__ = ["assistant_router"]
