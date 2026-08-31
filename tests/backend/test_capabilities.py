"""Capability domain model guarantees (Phase 2A-A)."""

from __future__ import annotations

import unittest

from app.agents.capabilities import (
    AgentDescriptor,
    CapabilitySection,
    CapabilitySnapshot,
    ModelDescriptor,
    UnavailabilityReason,
    UnavailableCapability,
    items_or_empty,
)


class CapabilityModelTests(unittest.TestCase):
    def test_empty_and_unavailable_are_distinguishable(self) -> None:
        empty = CapabilitySection[ModelDescriptor]()
        unavailable = CapabilitySection[ModelDescriptor](
            items=(),
            unavailable=UnavailableCapability(
                UnavailabilityReason.NOT_EXPOSED_BY_PROVIDER, "provider said nothing"
            ),
        )
        self.assertTrue(empty.available)
        self.assertTrue(empty.is_empty_but_available)
        self.assertFalse(unavailable.available)
        self.assertFalse(unavailable.is_empty_but_available)

    def test_unavailability_has_machine_reason_and_human_message(self) -> None:
        un = UnavailableCapability(
            UnavailabilityReason.PENDING_DISCOVERY, "Discovery arrives in Phase 2A-B."
        )
        self.assertIsInstance(un.reason.value, str)
        self.assertEqual(un.reason, UnavailabilityReason.PENDING_DISCOVERY)
        self.assertTrue(len(un.message) > 0)

    def test_snapshot_defaults_invent_nothing(self) -> None:
        snap = CapabilitySnapshot(source="test")
        for section in (snap.models, snap.modes, snap.thinking_options, snap.commands):
            self.assertEqual(section.items, ())
            self.assertIsNotNone(section.unavailable)
        self.assertIsInstance(snap.agent, UnavailableCapability)
        self.assertIsInstance(snap.attachments, UnavailableCapability)
        self.assertIsInstance(snap.sessions, UnavailableCapability)

    def test_snapshot_carries_source_and_freshness(self) -> None:
        first = CapabilitySnapshot(source="acp:opencode")
        second = CapabilitySnapshot(source="acp:opencode")
        self.assertEqual(first.source, "acp:opencode")
        self.assertLessEqual(first.captured_at, second.captured_at)

    def test_populated_sections_expose_runtime_descriptors(self) -> None:
        section: CapabilitySection[AgentDescriptor] = CapabilitySection(
            items=(AgentDescriptor(id="opencode", label="OpenCode"),)
        )
        self.assertEqual(len(items_or_empty(section)), 1)


if __name__ == "__main__":
    unittest.main()
