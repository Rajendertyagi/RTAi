"""Benchmark instrumentation guarantees (Phase 2A-B cases 15-16)."""

from __future__ import annotations

import json
import unittest

from app.agents.benchmark import BenchmarkRecorder, SystemClock


class FakeClock:
    """Deterministic monotonic clock advancing on every read."""

    def __init__(self) -> None:
        self.now = 100.0

    def monotonic(self) -> float:
        self.now += 0.25
        return self.now


class BenchmarkRecorderTests(unittest.TestCase):
    def test_deterministic_timestamps_with_injected_clock(self) -> None:
        recorder = BenchmarkRecorder(adapter="opencode_server", clock=FakeClock().monotonic)
        recorder.mark("startup")
        recorder.mark("ready")
        recorder.mark("session_created")
        recorder.mark("prompt_accepted")
        recorder.mark("first_event")
        recorder.mark("first_token")
        recorder.mark("completed")
        result = recorder.to_json_dict()
        metrics = result["metrics_seconds"]
        self.assertEqual(metrics["startup"], 0.0)
        self.assertEqual(metrics["ready"], 0.25)
        self.assertEqual(metrics["first_token"], 1.25)
        self.assertEqual(metrics["completed"], 1.5)

    def test_unknown_milestones_are_rejected(self) -> None:
        recorder = BenchmarkRecorder(adapter="x", clock=FakeClock().monotonic)
        with self.assertRaises(ValueError):
            recorder.mark("user_text")

    def test_unset_milestones_serialize_as_null(self) -> None:
        recorder = BenchmarkRecorder(adapter="x", clock=FakeClock().monotonic)
        recorder.mark("startup")
        payload = json.loads(recorder.to_json())
        self.assertIsNone(payload["metrics_seconds"]["completed"])
        self.assertIsNone(payload["error_category"])

    def test_records_never_contain_prompt_or_credential_data(self) -> None:
        recorder = BenchmarkRecorder(adapter="opencode_acp", clock=FakeClock().monotonic)
        recorder.mark("prompt_accepted")
        recorder.set_runtime_id("model", "prov/model-a")
        recorder.set_runtime_id("session", "session-owned-1")
        serialized = json.dumps(recorder.to_json_dict())
        for forbidden in ("secret", "password", "OPENCODE_SERVER_PASSWORD"):
            self.assertNotIn(forbidden.lower(), serialized.lower())

    def test_error_category_is_recorded(self) -> None:
        recorder = BenchmarkRecorder(adapter="x", clock=SystemClock().monotonic)
        recorder.fail("provider_error")
        self.assertEqual(recorder.to_json_dict()["error_category"], "provider_error")


if __name__ == "__main__":
    unittest.main()
