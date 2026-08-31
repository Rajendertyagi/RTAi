"""ACP runtime discovery mapping (Phase 2A-B cases 1-4)."""

from __future__ import annotations

import unittest

from app.agents.opencode.capability_mapper import AcpCapabilityState

MODEL_OPTION = {
    "id": "cfg-model",
    "name": "Model",
    "type": "select",
    "category": "model",
    "currentValue": "prov/a",
    "options": [
        {"value": "prov/a", "name": "Alpha"},
        {"value": "prov/b", "name": "Beta"},
    ],
}

THOUGHT_OPTION_AFTER_A = {
    "id": "cfg-effort",
    "name": "Effort",
    "type": "select",
    "category": "thought_level",
    "currentValue": "high",
    "options": [{"value": "high", "name": "High"}],
}

THOUGHT_OPTION_AFTER_B = {
    "id": "cfg-effort",
    "name": "Effort",
    "type": "select",
    "category": "thought_level",
    "currentValue": "low",
    "options": [
        {"value": "low", "name": "Low"},
        {"value": "high", "name": "High"},
    ],
}

MODE_OPTION = {
    "id": "cfg-mode",
    "name": "Mode",
    "type": "select",
    "category": "mode",
    "currentValue": "code",
    "options": [
        {"value": "build", "name": "Build"},
        {"value": "code", "name": "Code"},
    ],
}


class AcpDiscoveryTests(unittest.TestCase):
    def test_model_mode_thinking_discovery(self) -> None:
        state = AcpCapabilityState()
        state.ingest_config_options([MODEL_OPTION, THOUGHT_OPTION_AFTER_A, MODE_OPTION])
        self.assertEqual([m.id for m in state.models.items], ["prov/a", "prov/b"])
        self.assertEqual(state.selected_model, "prov/a")
        self.assertEqual([t.id for t in state.thinking.items], ["high"])
        self.assertEqual(state.selected_thinking, "high")
        self.assertEqual([m.id for m in state.modes.items], ["build", "code"])
        # Runtime ids stay separate from labels and config ids are remembered.
        self.assertEqual(state.models.items[0].label, "Alpha")
        self.assertEqual(state.model_config_id, "cfg-model")
        self.assertEqual(state.thought_level_config_id, "cfg-effort")
        self.assertEqual(state.mode_config_id, "cfg-mode")

    def test_model_change_refreshes_model_specific_thinking(self) -> None:
        state = AcpCapabilityState()
        state.ingest_config_options(
            [dict(MODEL_OPTION, currentValue="prov/a"), THOUGHT_OPTION_AFTER_A]
        )
        self.assertEqual([t.id for t in state.thinking.items], ["high"])
        # Model switch: the agent echoes the COMPLETE option list with new
        # thought-level entries; sections are replaced authoritatively.
        state.ingest_config_options(
            [dict(MODEL_OPTION, currentValue="prov/b"), THOUGHT_OPTION_AFTER_B]
        )
        self.assertEqual(state.selected_model, "prov/b")
        self.assertEqual(
            [t.id for t in state.thinking.items], ["low", "high"]
        )
        self.assertEqual(state.thinking.items[0].model_id, "prov/b")

    def test_unknown_config_categories_are_ignored_safely(self) -> None:
        state = AcpCapabilityState()
        weird = {
            "id": "cfg-weird",
            "name": "Weird",
            "type": "select",
            "category": "_custom_experimental",
            "currentValue": "x",
            "options": [{"value": "x", "name": "X"}],
        }
        non_select = {"id": "cfg-b", "name": "B", "type": "boolean", "currentValue": True}
        state.ingest_config_options([weird, non_select])
        # Unknown categories are ignored: slices stay empty-but-available.
        for section in (state.models, state.thinking, state.modes):
            self.assertTrue(section.is_empty_but_available)
            self.assertIsNone(section.unavailable)
        self.assertIsNone(state.model_config_id)

    def test_missing_capabilities_carry_unavailable_reasons(self) -> None:
        state = AcpCapabilityState()
        for section in (state.models, state.thinking, state.modes, state.commands):
            # Unknown/boolean categories are ignored: slices stay empty but
            # available, clearly distinct from an unavailable marker below.
            self.assertTrue(section.available)
            self.assertTrue(section.is_empty_but_available)
            self.assertIsNone(section.unavailable)
        explicit = unavailable_marker("endpoint missing")
        self.assertFalse(explicit.available)
        assert explicit.unavailable is not None
        self.assertEqual(explicit.unavailable.reason.value, "not_exposed_by_provider")


def unavailable_marker(message: str):
    from app.agents.capabilities import (
        CapabilitySection,
        UnavailabilityReason,
        UnavailableCapability,
    )

    return CapabilitySection(
        items=(),
        unavailable=UnavailableCapability(
            UnavailabilityReason.NOT_EXPOSED_BY_PROVIDER, message
        ),
    )


if __name__ == "__main__":
    unittest.main()
