"""Model selection must be re-applied on the live session before each prompt.

The ACP prompt request carries no model field, so the effective model for a turn
depends entirely on the session config applied via ``set_config_option``. After a
user selects a model, the next prompt must re-assert that selection through the
single authorized config path (the same one ``select()`` uses) - no second
selection UI and no hardcoded model. This is the regression guard for Issue 1.
"""
from __future__ import annotations

import unittest

from app.agents.opencode_acp import OpenCodeSession


class RecordingModelConnection:
    """Records set_config_option + prompt calls for the model-lifecycle checks."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def set_config_option(self, session_id, config_id, value):
        self.calls.append(
            {"kind": "set_config_option", "config_id": config_id, "value": value}
        )
        # Echo the applied config so the adapter can fold it back via
        # ingest_config_options, mirroring the real ACP response shape.
        return {
            "configOptions": [
                {
                    "id": config_id,
                    "type": "select",
                    "category": "model" if "model" in config_id else "thought_level",
                    "currentValue": value,
                    "options": [{"value": value, "name": value}],
                }
            ]
        }

    async def prompt(self, session_id, prompt):
        self.calls.append({"kind": "prompt", "prompt": prompt})


def session_with_selected_model(model_value: str = "prov/b"):
    session = OpenCodeSession()
    conn = RecordingModelConnection()
    session._connection = conn  # noqa: SLF001 - white-box harness
    session._session_id = "session-1"
    session._emit = None
    from app.agents.opencode.capability_mapper import AcpCapabilityState

    caps = AcpCapabilityState()
    caps.ingest_config_options(
        [
            {
                "id": "cfg-model",
                "type": "select",
                "category": "model",
                "currentValue": "prov/a",
                "options": [
                    {"value": "prov/a", "name": "A"},
                    {"value": "prov/b", "name": "B"},
                ],
            }
        ]
    )
    caps.selected_model = model_value
    session._capabilities = caps
    return session, conn


class ModelReassertTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_prompt_reasserts_selected_model(self) -> None:
        session, conn = session_with_selected_model("prov/b")
        await session.submit_prompt("hello")
        # The re-asserted config option must precede the prompt call.
        self.assertEqual(conn.calls[0]["kind"], "set_config_option")
        self.assertEqual(conn.calls[0]["config_id"], "cfg-model")
        self.assertEqual(conn.calls[0]["value"], "prov/b")
        self.assertEqual(conn.calls[1]["kind"], "prompt")

    async def test_submit_prompt_content_reasserts_selected_model(self) -> None:
        session, conn = session_with_selected_model("prov/b")
        from app.agents.prompt_content import PromptContent, PromptKind

        await session.submit_prompt_content(
            [PromptContent(kind=PromptKind.TEXT, name="msg", text="hi")]
        )
        self.assertEqual(conn.calls[0]["kind"], "set_config_option")
        self.assertEqual(conn.calls[0]["value"], "prov/b")
        self.assertEqual(conn.calls[1]["kind"], "prompt")

    async def test_no_reassert_when_no_model_selected(self) -> None:
        session, conn = session_with_selected_model("prov/b")
        session._capabilities.selected_model = None
        await session.submit_prompt("hello")
        self.assertEqual([c["kind"] for c in conn.calls], ["prompt"])


if __name__ == "__main__":
    unittest.main()
