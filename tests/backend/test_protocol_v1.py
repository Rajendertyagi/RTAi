"""Protocol v1 normalization, validation and capability mapping tests."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import MagicMock

from app.agents.capabilities import (
    AgentDescriptor,
    CapabilitySection,
    CapabilitySnapshot,
    UnavailabilityReason,
    UnavailableCapability,
)
from app.api.protocol_v1 import (
    PROTOCOL_VERSION,
    PermissionTracker,
    normalize_emission,
    snapshot_to_v1_events,
    validate_command,
)


class CommandValidationTests(unittest.TestCase):
    def test_valid_prompt_accepted(self) -> None:
        valid, err = validate_command({
            "protocol_version": 1,
            "type": "prompt",
            "request_id": "r1",
            "session_id": "s1",
            "turn_id": "t1",
            "message_id": "m1",
            "text": "hello",
        })
        self.assertTrue(valid)
        self.assertIsNone(err)

    def test_prompt_missing_text_rejected(self) -> None:
        valid, err = validate_command({
            "protocol_version": 1,
            "type": "prompt",
            "session_id": "s1",
            "turn_id": "t1",
            "message_id": "m1",
        })
        self.assertFalse(valid)
        self.assertIsNotNone(err)

    def test_wrong_protocol_version_rejected(self) -> None:
        valid, err = validate_command({
            "protocol_version": 2,
            "type": "prompt",
            "session_id": "s1",
            "turn_id": "t1",
            "message_id": "m1",
            "text": "hi",
        })
        self.assertFalse(valid)
        self.assertEqual(err, "unsupported_protocol_version")

    def test_unknown_command_rejected(self) -> None:
        valid, err = validate_command({
            "protocol_version": 1,
            "type": "foobar",
        })
        self.assertFalse(valid)
        self.assertEqual(err, "unknown_command")

    def test_cancel_valid(self) -> None:
        valid, err = validate_command({
            "protocol_version": 1,
            "type": "cancel",
            "session_id": "s1",
            "turn_id": "t1",
        })
        self.assertTrue(valid)
        self.assertIsNone(err)

    def test_select_model_missing_model_id(self) -> None:
        valid, err = validate_command({
            "protocol_version": 1,
            "type": "select_model",
            "session_id": "s1",
        })
        self.assertFalse(valid)
        self.assertIsNotNone(err)

    def test_permission_response_full(self) -> None:
        valid, err = validate_command({
            "protocol_version": 1,
            "type": "permission_response",
            "session_id": "s1",
            "turn_id": "t1",
            "permission_request_id": "p1",
            "option_id": "opt-1",
        })
        self.assertTrue(valid)
        self.assertIsNone(err)


class NormalizationTests(unittest.TestCase):
    def test_envelope_added(self) -> None:
        result = normalize_emission(
            {"type": "delta", "text": "hi"},
            session_id="s1",
            turn_id="t1",
            sequence=0,
        )
        self.assertEqual(result["protocol_version"], PROTOCOL_VERSION)
        self.assertEqual(result["session_id"], "s1")
        self.assertEqual(result["turn_id"], "t1")
        self.assertEqual(result["type"], "delta")
        self.assertEqual(result["text"], "hi")

    def test_sequence_injected_for_delta(self) -> None:
        result = normalize_emission(
            {"type": "delta", "text": "x"},
            session_id="s1",
            turn_id="t1",
            sequence=5,
        )
        self.assertEqual(result["sequence"], 5)

    def test_sequence_not_overwritten(self) -> None:
        result = normalize_emission(
            {"type": "delta", "text": "x", "sequence": 99},
            session_id="s1",
            turn_id="t1",
            sequence=5,
        )
        self.assertEqual(result["sequence"], 99)

    def test_envelope_fields_cannot_be_overwritten(self) -> None:
        result = normalize_emission(
            {"type": "delta", "protocol_version": 99, "session_id": "hacked"},
            session_id="s1",
            turn_id="t1",
            sequence=0,
        )
        self.assertEqual(result["protocol_version"], PROTOCOL_VERSION)
        self.assertEqual(result["session_id"], "s1")

    def test_turn_id_optional(self) -> None:
        result = normalize_emission(
            {"type": "agent_info", "name": "opencode"},
            session_id="s1",
            turn_id=None,
            sequence=0,
        )
        self.assertNotIn("turn_id", result)


class CapabilityMappingTests(unittest.TestCase):
    def test_available_models_emit_items(self) -> None:
        snap = CapabilitySnapshot(
            source="test",
            models=CapabilitySection(items=(
                MagicMock(id="m1", label="Model 1"),
            )),
        )
        events = snapshot_to_v1_events(snap)
        models_ev = [e for e in events if e["type"] == "models_available"][0]
        self.assertTrue(models_ev["available"])
        self.assertEqual(len(models_ev["models"]), 1)
        self.assertEqual(models_ev["models"][0]["id"], "m1")

    def test_unavailable_models_emit_reason(self) -> None:
        snap = CapabilitySnapshot(
            source="test",
            models=CapabilitySection(
                items=(),
                unavailable=UnavailableCapability(
                    UnavailabilityReason.NOT_EXPOSED_BY_PROVIDER,
                    "No providers configured",
                ),
            ),
        )
        events = snapshot_to_v1_events(snap)
        models_ev = [e for e in events if e["type"] == "models_available"][0]
        self.assertFalse(models_ev["available"])
        self.assertEqual(models_ev["reason_code"], "not_exposed_by_provider")
        self.assertEqual(
            models_ev["reason_message"],
            "No providers configured",
        )

    def test_empty_but_available_models_emit_empty_list(self) -> None:
        snap = CapabilitySnapshot(
            source="test",
            models=CapabilitySection(items=()),
        )
        events = snapshot_to_v1_events(snap)
        models_ev = [e for e in events if e["type"] == "models_available"][0]
        self.assertTrue(models_ev["available"])
        self.assertEqual(models_ev["models"], [])

    def test_agent_info_emitted_when_available(self) -> None:
        snap = CapabilitySnapshot(
            source="test",
            agent=AgentDescriptor(id="oc", label="opencode"),
        )
        events = snapshot_to_v1_events(snap)
        info = [e for e in events if e["type"] == "agent_info"]
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0]["name"], "opencode")

    def test_agent_info_not_emitted_when_unavailable(self) -> None:
        snap = CapabilitySnapshot(
            source="test",
            agent=UnavailableCapability(
                UnavailabilityReason.PENDING_DISCOVERY, "Not yet"
            ),
        )
        events = snapshot_to_v1_events(snap)
        self.assertEqual(
            [e for e in events if e["type"] == "agent_info"],
            [],
        )

    def test_thinking_available_with_levels(self) -> None:
        from app.agents.capabilities import ThinkingOption
        snap = CapabilitySnapshot(
            source="test",
            thinking_options=CapabilitySection(
                items=(ThinkingOption(id="low", label="Low"),)
            ),
        )
        events = snapshot_to_v1_events(snap)
        th = [e for e in events if e["type"] == "thinking_available"][0]
        self.assertTrue(th["available"])
        self.assertEqual(th["thinking_levels"], ["low"])

    def test_thinking_unavailable_emits_reason(self) -> None:
        snap = CapabilitySnapshot(
            source="test",
            thinking_options=CapabilitySection(
                items=(),
                unavailable=UnavailableCapability(
                    UnavailabilityReason.NOT_EXPOSED_BY_PROVIDER,
                    "No variants",
                ),
            ),
        )
        events = snapshot_to_v1_events(snap)
        th = [e for e in events if e["type"] == "thinking_available"][0]
        self.assertFalse(th["available"])
        self.assertEqual(th["reason_code"], "not_exposed_by_provider")


class PermissionTrackerTests(unittest.TestCase):
    def test_resolve_known_id(self) -> None:
        tracker = PermissionTracker(timeout_seconds=1.0)
        loop = asyncio.new_event_loop()
        fut = loop.create_future()
        tracker.register("perm-1", fut)
        result = tracker.resolve("perm-1", "allow")
        self.assertTrue(result)
        self.assertTrue(fut.done())
        self.assertEqual(loop.run_until_complete(fut), "allow")
        loop.close()

    def test_resolve_unknown_id_returns_false(self) -> None:
        tracker = PermissionTracker()
        result = tracker.resolve("nope", "x")
        self.assertFalse(result)

    def test_reject_unknown_cancels_nothing(self) -> None:
        tracker = PermissionTracker()
        result = tracker.reject_unknown("nope")
        self.assertFalse(result)

    def test_cancel_all_resolves_pending(self) -> None:
        tracker = PermissionTracker()
        loop = asyncio.new_event_loop()
        fut = loop.create_future()
        tracker.register("p1", fut)
        tracker.cancel_all()
        self.assertTrue(fut.cancelled())
        loop.close()

    def test_has_pending(self) -> None:
        tracker = PermissionTracker()
        self.assertFalse(tracker.has_pending)
        loop = asyncio.new_event_loop()
        fut = loop.create_future()
        tracker.register("p1", fut)
        self.assertTrue(tracker.has_pending)
        loop.close()


if __name__ == "__main__":
    unittest.main()
