"""Adapter selection setting: strict, no silent fallback (Phase 2A-B case 8-9)."""

from __future__ import annotations

import unittest

from app.agents.factory import (
    OpenCodeAdapterFactory,
    ServerAdapterFactory,
    create_default_factory,
)
from app.agents.runtime_settings import (
    AdapterSelectionError,
    resolve_adapter_kind,
    resolve_from_environment,
)


class AdapterSelectionTests(unittest.TestCase):
    def test_unset_resolves_to_acp_preserving_current_behavior(self) -> None:
        self.assertEqual(resolve_adapter_kind(None), "opencode_acp")
        self.assertEqual(resolve_adapter_kind(""), "opencode_acp")
        self.assertEqual(resolve_from_environment({}), "opencode_acp")

    def test_valid_kinds_resolve_case_insensitively(self) -> None:
        self.assertEqual(resolve_adapter_kind("opencode_server"), "opencode_server")
        self.assertEqual(resolve_adapter_kind("  OpenCode_ACP "), "opencode_acp")

    def test_invalid_kind_fails_loudly_listing_valid_values(self) -> None:
        with self.assertRaises(AdapterSelectionError) as caught:
            resolve_adapter_kind("codex")
        message = str(caught.exception)
        self.assertIn("RTAI_OPENCODE_ADAPTER", message)
        self.assertIn("opencode_server", message)
        self.assertIn("opencode_acp", message)

    def test_environment_resolution_reads_given_mapping(self) -> None:
        self.assertEqual(
            resolve_from_environment({"RTAI_OPENCODE_ADAPTER": "opencode_server"}),
            "opencode_server",
        )

    def test_factory_matches_configured_kind_without_fallback(self) -> None:
        acp_factory = create_default_factory({"RTAI_OPENCODE_ADAPTER": "opencode_acp"})
        server_factory = create_default_factory(
            {"RTAI_OPENCODE_ADAPTER": "opencode_server"}
        )
        self.assertIsInstance(acp_factory, OpenCodeAdapterFactory)
        self.assertIsInstance(server_factory, ServerAdapterFactory)

    def test_invalid_configuration_raises_at_startup(self) -> None:
        with self.assertRaises(AdapterSelectionError):
            create_default_factory({"RTAI_OPENCODE_ADAPTER": "definitely-wrong"})

    def test_adapters_are_fresh_instances_per_session(self) -> None:
        factory = create_default_factory({})
        first = factory.create()
        second = factory.create()
        self.assertIsNot(first, second)


if __name__ == "__main__":
    unittest.main()
