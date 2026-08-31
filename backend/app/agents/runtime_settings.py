"""Explicit backend adapter selection (Phase 2A-B).

The selector is intentionally strict:

- Unset resolves to ``opencode_acp``, preserving the pre-existing user-facing
  behavior (this is a configured default, not a cross-adapter fallback).
- Anything other than the two known kinds raises immediately - there is never
  a silent fallback from one adapter to another.
"""

from __future__ import annotations

import os

ADAPTER_ENV_KEY = "RTAI_OPENCODE_ADAPTER"
VALID_ADAPTER_KINDS = ("opencode_server", "opencode_acp")
DEFAULT_ADAPTER_KIND = "opencode_acp"


class AdapterSelectionError(ValueError):
    """Raised when the configured adapter kind is not recognized."""


def resolve_adapter_kind(raw_value: str | None) -> str:
    value = (raw_value or "").strip().lower()
    if not value:
        return DEFAULT_ADAPTER_KIND
    if value not in VALID_ADAPTER_KINDS:
        valid = ", ".join(VALID_ADAPTER_KINDS)
        raise AdapterSelectionError(
            f"Unknown {ADAPTER_ENV_KEY} value {raw_value!r}; expected one of: {valid}"
        )
    return value


def resolve_from_environment(environ: dict[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    return resolve_adapter_kind(source.get(ADAPTER_ENV_KEY))
