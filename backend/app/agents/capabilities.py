"""Provider-neutral capability domain models (Phase 2A-A).

These models describe what an agent CAN do as discovered at runtime. They are
deliberately boring: identifiers are separated from display labels, absence is
distinguished from emptiness, and every unavailability carries a machine
readable reason plus a user-facing message. Nothing here may be populated with
invented production values - adapters fill snapshots exclusively from what the
provider actually reported.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any, Generic, TypeVar


class UnavailabilityReason(str, Enum):
    """Stable, machine-readable vocabulary for why a capability is absent."""

    NOT_EXPOSED_BY_PROVIDER = "not_exposed_by_provider"
    PENDING_DISCOVERY = "pending_discovery"
    NEGOTIATION_FAILED = "negotiation_failed"


@dataclass(frozen=True)
class UnavailableCapability:
    """Marks a capability as not usable right now, and says why."""

    reason: UnavailabilityReason
    message: str


@dataclass(frozen=True)
class AgentDescriptor:
    id: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class ModelDescriptor:
    id: str
    label: str


@dataclass(frozen=True)
class ModeDescriptor:
    id: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class ThinkingOption:
    """One reasoning-effort choice, scoped to the model that announced it."""

    id: str
    label: str
    model_id: str = ""


@dataclass(frozen=True)
class CommandDescriptor:
    name: str
    description: str = ""
    input_hint: str = ""


@dataclass(frozen=True)
class AttachmentCapabilities:
    """Block kinds the provider accepts plus optional local policy limit."""

    block_types: tuple[str, ...] = ()
    max_size_bytes: int | None = None  # None = unknown, deliberately not a number
    # Per-kind support derived from ACP promptCapabilities negotiation.
    resource_links: bool = True  # baseline per ACP v1 spec
    images: bool = False
    audio: bool = False
    embedded_resources: bool = False
    # RTAI safety limits (applied regardless of provider limits).
    max_item_bytes: int = 5 * 1024 * 1024  # 5 MiB per attachment
    max_total_bytes: int = 10 * 1024 * 1024  # 10 MiB per prompt
    max_count: int = 10


@dataclass(frozen=True)
class SessionCapabilities:
    """Tri-state session features: True supported, False unsupported, None unknown."""

    load: bool | None = None
    resume: bool | None = None
    close: bool | None = None
    list_sessions: bool | None = None
    delete: bool | None = None
    additional_directories: bool | None = None


T = TypeVar("T")


@dataclass(frozen=True)
class CapabilitySection(Generic[T]):
    """
    One named slice of a snapshot.

    ``unavailable is None`` means the provider answered: ``items`` may still be
    empty (a genuine "none available"). A set ``unavailable`` means the slice
    could not be discovered at all, with the reason attached.
    """

    items: tuple[T, ...] = ()
    unavailable: UnavailableCapability | None = None

    @property
    def available(self) -> bool:
        return self.unavailable is None

    @property
    def is_empty_but_available(self) -> bool:
        return self.unavailable is None and len(self.items) == 0


def unavailable_section(reason: UnavailabilityReason, message: str) -> CapabilitySection[object]:
    return CapabilitySection(items=(), unavailable=UnavailableCapability(reason, message))


def _pending_unavailable() -> UnavailableCapability:
    return UnavailableCapability(
        UnavailabilityReason.PENDING_DISCOVERY,
        "Capability discovery arrives in Phase 2A-B.",
    )


def _pending_section() -> CapabilitySection[Any]:
    return CapabilitySection(items=(), unavailable=_pending_unavailable())


@dataclass(frozen=True)
class CapabilitySnapshot:
    """Point-in-time answer to 'what can this agent do?'."""

    source: str
    captured_at: float = field(default_factory=time)
    agent: AgentDescriptor | UnavailableCapability = field(default_factory=_pending_unavailable)
    agents: CapabilitySection[AgentDescriptor] = field(
        default_factory=lambda: CapabilitySection(
            items=(),
            unavailable=_pending_unavailable(),
        )
    )
    models: CapabilitySection[ModelDescriptor] = field(default_factory=_pending_section)
    modes: CapabilitySection[ModeDescriptor] = field(default_factory=_pending_section)
    thinking_options: CapabilitySection[ThinkingOption] = field(default_factory=_pending_section)
    commands: CapabilitySection[CommandDescriptor] = field(default_factory=_pending_section)
    attachments: AttachmentCapabilities | UnavailableCapability = field(
        default_factory=lambda: UnavailableCapability(
            UnavailabilityReason.PENDING_DISCOVERY,
            "Attachment support is negotiated during initialization.",
        )
    )
    sessions: SessionCapabilities | UnavailableCapability = field(
        default_factory=_pending_unavailable
    )


def items_or_empty(section: CapabilitySection[T]) -> Sequence[T]:
    """Convenience accessor for consumers that treat unavailable as empty."""
    return section.items if section.available else ()
