"""ACP selection semantics using received config ids only (Phase 2A-B)."""

from __future__ import annotations

import unittest

from app.agents.opencode_acp import OpenCodeSession


class RecordingConnection:
    """Fake connection recording selection calls; can simulate failures."""

    def __init__(self, fail_config_ids: set[str] | None = None) -> None:
        self.calls: list[dict[str, str]] = []
        self.fail_config_ids = fail_config_ids or set()

    async def set_config_option(
        self, session_id: str, config_id: str, value: str
    ) -> dict[str, object]:
        self.calls.append({"config_id": config_id, "value": value})
        if config_id in self.fail_config_ids:
            raise RuntimeError("runtime rejected the value")
        # Spec: response carries the complete configuration state.
        return {
            "configOptions": [
                {
                    "id": config_id,
                    "name": config_id,
                    "type": "select",
                    "category": "model" if "model" in config_id else "thought_level",
                    "currentValue": value,
                    "options": [{"value": value, "name": value}],
                }
            ]
        }

    async def set_session_mode(self, session_id: str, mode_id: str) -> dict[str, object]:
        self.calls.append({"mode_id": mode_id})
        return {}


def adapter_with_state(
    session_id: str = "session-1",
) -> tuple[OpenCodeSession, RecordingConnection]:
    session = OpenCodeSession()
    connection = RecordingConnection()
    session._connection = connection  # noqa: SLF001 - white-box harness
    session._session_id = session_id
    from app.agents.opencode.capability_mapper import AcpCapabilityState

    caps = AcpCapabilityState()
    caps.ingest_config_options(
        [
            {
                "id": "cfg-model-received",
                "type": "select",
                "category": "model",
                "currentValue": "prov/a",
                "options": [{"value": "prov/a", "name": "A"}, {"value": "prov/b", "name": "B"}],
            },
            {
                "id": "cfg-effort-received",
                "type": "select",
                "category": "thought_level",
                "currentValue": "off",
                "options": [{"value": "off", "name": "Off"}],
            },
        ]
    )
    session._capabilities = caps  # noqa: SLF001
    return session, connection


class AcpSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_selection_uses_received_config_id(self) -> None:
        session, connection = adapter_with_state()
        result = await session.select("model", "prov/b")
        self.assertTrue(result.applied)
        self.assertEqual(len(connection.calls), 1)
        call = connection.calls[0]
        self.assertEqual(call["config_id"], "cfg-model-received")
        self.assertEqual(call["value"], "prov/b")
        # The returned runtime state is authoritative.
        self.assertEqual(session._capabilities.selected_model, "prov/b")

    async def test_thinking_selection_uses_thought_level_config_id(self) -> None:
        session, connection = adapter_with_state()
        result = await session.select("thinking", "high")
        self.assertTrue(result.applied)
        self.assertEqual(connection.calls[0]["config_id"], "cfg-effort-received")

    async def test_runtime_failure_returns_non_applied_result(self) -> None:
        session, connection = adapter_with_state()
        connection.fail_config_ids.add("cfg-model-received")
        result = await session.select("model", "prov/z")
        self.assertFalse(result.applied)
        self.assertIn("rejected", result.message)

    async def test_unannounced_capability_reports_disabled_reason(self) -> None:
        session, connection = adapter_with_state()
        session._capabilities.thought_level_config_id = None
        result = await session.select("thinking", "high")
        self.assertFalse(result.applied)
        self.assertIn("No thinking config option", result.message)
        self.assertEqual(connection.calls, [])

    async def test_not_ready_session_disables_selection(self) -> None:
        bare = OpenCodeSession()
        result = await bare.select("model", "x")
        self.assertFalse(result.applied)


if __name__ == "__main__":
    unittest.main()
