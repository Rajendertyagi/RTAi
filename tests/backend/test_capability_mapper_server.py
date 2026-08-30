"""OpenCode Server API capability mapping (Phase 2A-B cases 5-6)."""

from __future__ import annotations

import unittest

from app.agents.opencode.capability_mapper import (
    server_models_from_providers,
    server_selected_model,
)

PROVIDERS = {
    "anthropic": {
        "id": "anthropic",
        "name": "Anthropic",
        "models": {
            "claude-sonnet-4": {"id": "claude-sonnet-4", "name": "Claude Sonnet 4"},
            "claude-haiku": {"name": "Claude Haiku"},
        },
    },
    "openai": {
        "models": [
            {"id": "gpt-5", "name": "GPT-5"},
        ]
    },
}


class ServerMappingTests(unittest.TestCase):
    def test_providers_flatten_to_provider_scoped_models(self) -> None:
        models = server_models_from_providers(PROVIDERS)
        ids = [m.id for m in models]
        self.assertIn("anthropic/claude-sonnet-4", ids)
        self.assertIn("anthropic/claude-haiku", ids)
        self.assertIn("openai/gpt-5", ids)
        labels = {m.id: m.label for m in models}
        self.assertEqual(labels["anthropic/claude-sonnet-4"], "Claude Sonnet 4")
        self.assertEqual(labels["anthropic/claude-haiku"], "Claude Haiku")
        # A nameless model falls back to the runtime id, never invented text.
        self.assertEqual(labels["openai/gpt-5"], "GPT-5")

    def test_selected_model_from_config_dict_and_string_forms(self) -> None:
        self.assertEqual(
            server_selected_model({"model": {"providerID": "a", "modelID": "b"}}),
            "a/b",
        )
        self.assertEqual(server_selected_model({"model": "a/b"}), "a/b")
        self.assertIsNone(server_selected_model({}))
        self.assertIsNone(server_selected_model(None))

    def test_unsupported_payload_shapes_yield_empty_not_invented(self) -> None:
        self.assertEqual(server_models_from_providers(None), [])
        self.assertEqual(server_models_from_providers("nonsense"), [])


if __name__ == "__main__":
    unittest.main()
