"""Client diagnostic command validation for safe observability (Task 2).

Drives the REAL ``RtaiClientDiagnosticCommand`` Pydantic model and the REAL
``prepare_validated_commands`` path from ``app.transport.assistant.models``.

Locks the contract:
- ``tool_group_visibility`` accepts ONLY the required ``status``/``open``/
  ``toolCount`` fields (plus the fixed ``type``/``event``).
- Missing any required field is rejected.
- Supplying those fields on ANY other diagnostic event is rejected.
- Invalid ``status`` and out-of-range ``toolCount`` (``<0`` / ``>256``) are
  rejected.
- All pre-existing diagnostic events remain accepted (no regression).
"""

from __future__ import annotations

import unittest
from typing import Any

from pydantic import ValidationError

from app.transport.assistant.models import (
    RTAI_CLIENT_DIAGNOSTIC_COMMAND,
    RtaiClientDiagnosticCommand,
    prepare_validated_commands,
)


def _cmd(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"type": RTAI_CLIENT_DIAGNOSTIC_COMMAND}
    base.update(overrides)
    return base


class ToolGroupVisibilityValidationTests(unittest.TestCase):
    def test_accepts_valid_tool_group_visibility(self) -> None:
        cmd = _cmd(
            event="tool_group_visibility",
            status="running",
            open=False,
            toolCount=3,
        )
        model = RtaiClientDiagnosticCommand.model_validate(cmd)
        self.assertEqual(model.event, "tool_group_visibility")
        self.assertEqual(model.status, "running")
        self.assertEqual(model.open, False)
        self.assertEqual(model.toolCount, 3)

    def test_missing_status_rejected(self) -> None:
        cmd = _cmd(event="tool_group_visibility", open=True, toolCount=1)
        with self.assertRaises(ValidationError):
            RtaiClientDiagnosticCommand.model_validate(cmd)

    def test_missing_open_rejected(self) -> None:
        cmd = _cmd(event="tool_group_visibility", status="running", toolCount=1)
        with self.assertRaises(ValidationError):
            RtaiClientDiagnosticCommand.model_validate(cmd)

    def test_missing_tool_count_rejected(self) -> None:
        cmd = _cmd(event="tool_group_visibility", status="running", open=True)
        with self.assertRaises(ValidationError):
            RtaiClientDiagnosticCommand.model_validate(cmd)

    def test_status_enum_restricted(self) -> None:
        cmd = _cmd(
            event="tool_group_visibility",
            status="bogus-status",
            open=False,
            toolCount=2,
        )
        with self.assertRaises(ValidationError):
            RtaiClientDiagnosticCommand.model_validate(cmd)

    def test_tool_count_below_zero_rejected(self) -> None:
        cmd = _cmd(
            event="tool_group_visibility",
            status="running",
            open=False,
            toolCount=-1,
        )
        with self.assertRaises(ValidationError):
            RtaiClientDiagnosticCommand.model_validate(cmd)

    def test_tool_count_above_max_rejected(self) -> None:
        cmd = _cmd(
            event="tool_group_visibility",
            status="running",
            open=False,
            toolCount=257,
        )
        with self.assertRaises(ValidationError):
            RtaiClientDiagnosticCommand.model_validate(cmd)

    def test_tool_count_at_max_accepted(self) -> None:
        cmd = _cmd(
            event="tool_group_visibility",
            status="complete",
            open=True,
            toolCount=256,
        )
        model = RtaiClientDiagnosticCommand.model_validate(cmd)
        self.assertEqual(model.toolCount, 256)

    def test_fields_forbidden_on_gate_ready(self) -> None:
        cmd = _cmd(
            event="gate_ready",
            status="running",
            open=False,
            toolCount=1,
        )
        with self.assertRaises(ValidationError):
            RtaiClientDiagnosticCommand.model_validate(cmd)

    def test_fields_forbidden_on_permission_post_initiated(self) -> None:
        cmd = _cmd(
            event="permission_post_initiated",
            status="running",
            open=False,
            toolCount=1,
        )
        with self.assertRaises(ValidationError):
            RtaiClientDiagnosticCommand.model_validate(cmd)

    def test_fields_forbidden_on_client_error(self) -> None:
        cmd = _cmd(
            event="client_error",
            status="running",
            open=False,
            toolCount=1,
        )
        with self.assertRaises(ValidationError):
            RtaiClientDiagnosticCommand.model_validate(cmd)


class ExistingDiagnosticEventsStillAcceptedTests(unittest.TestCase):
    def test_gate_ready_accepted(self) -> None:
        model = RtaiClientDiagnosticCommand.model_validate(
            _cmd(event="gate_ready")
        )
        self.assertEqual(model.event, "gate_ready")

    def test_capability_command_sent_accepted(self) -> None:
        model = RtaiClientDiagnosticCommand.model_validate(
            _cmd(event="capability_command_sent", kind="refresh")
        )
        self.assertEqual(model.event, "capability_command_sent")

    def test_model_command_sent_accepted(self) -> None:
        model = RtaiClientDiagnosticCommand.model_validate(
            _cmd(event="model_command_sent", kind="model")
        )
        self.assertEqual(model.event, "model_command_sent")

    def test_permission_post_initiated_accepted(self) -> None:
        model = RtaiClientDiagnosticCommand.model_validate(
            _cmd(event="permission_post_initiated", optionLength=2)
        )
        self.assertEqual(model.event, "permission_post_initiated")
        self.assertEqual(model.optionLength, 2)

    def test_client_error_accepted(self) -> None:
        model = RtaiClientDiagnosticCommand.model_validate(
            _cmd(event="client_error", kind="transport")
        )
        self.assertEqual(model.event, "client_error")


class PrepareValidatedCommandsPathTests(unittest.TestCase):
    """End-to-end through the real prepare_validated_commands pipeline."""

    def test_tool_group_visibility_prepared_with_fields(self) -> None:
        prepared = prepare_validated_commands(
            [],
            [
                _cmd(
                    event="tool_group_visibility",
                    status="requires-action",
                    open=True,
                    toolCount=5,
                )
            ],
        )
        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared[0]["event"], "tool_group_visibility")
        self.assertEqual(prepared[0]["status"], "requires-action")
        self.assertEqual(prepared[0]["open"], True)
        self.assertEqual(prepared[0]["toolCount"], 5)

    def test_invalid_tool_group_visibility_rejected_by_pipeline(self) -> None:
        from fastapi.exceptions import RequestValidationError

        with self.assertRaises(RequestValidationError):
            prepare_validated_commands(
                [],
                [_cmd(event="tool_group_visibility", open=True, toolCount=1)],
            )


if __name__ == "__main__":
    unittest.main()
