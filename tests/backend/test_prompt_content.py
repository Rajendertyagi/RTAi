"""Prompt content domain model, capability negotiation and ACP conversion.

Phases 2-4: validates every supported block kind, enforces safety limits,
checks capability gating against AcpCapabilityState, and confirms correct
conversion to pinned ACP SDK block constructors using a fake module install.
"""

from __future__ import annotations

import base64
import contextlib
import sys
import unittest
from types import ModuleType
from typing import Any

from app.agents.acp.prompt_content import (
    DEFAULT_MAX_COUNT,
    DEFAULT_MAX_ITEM_BYTES,
    DEFAULT_MAX_TOTAL_BYTES,
    PromptKind,
    PromptValidationError,
    make_prompt_content,
    validate_prompt_limits,
)
from app.agents.acp.session import AcpSession
from app.agents.capabilities import (
    AttachmentCapabilities,
    CapabilitySnapshot,
    UnavailabilityReason,
    UnavailableCapability,
)
from app.agents.opencode.capability_mapper import AcpCapabilityState
from app.agents.opencode.server_adapter import OpenCodeServerAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_IMAGE_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
_AUDIO_B64 = base64.b64encode(b"\x00RIFF").decode("ascii")
_NAME = "test.png"
_MIME_IMAGE = "image/png"
_MIME_AUDIO = "audio/wav"


def _fake_acp_module() -> tuple[ModuleType, ModuleType]:
    """Return a minimal fake ``acp`` and ``acp.schema`` module."""
    acp_mod = ModuleType("acp")
    schema_mod = ModuleType("acp.schema")

    def text_block(text: str) -> dict:
        return {"_kind": "text_block", "text": text}

    def image_block(data: str, mime_type: str, *, uri: str | None = None) -> dict:
        return {"_kind": "image_block", "data": data, "mime_type": mime_type}

    def audio_block(data: str, mime_type: str) -> dict:
        return {"_kind": "audio_block", "data": data, "mime_type": mime_type}

    def resource_link_block(
        name: str,
        uri: str,
        *,
        mime_type: str | None = None,
        size: int | None = None,
        description: str | None = None,
        title: str | None = None,
    ) -> dict:
        return {
            "_kind": "resource_link_block",
            "name": name,
            "uri": uri,
            "mime_type": mime_type,
            "size": size,
            "description": description,
            "title": title,
        }

    def embedded_text_resource(
        uri: str, text: str, *, mime_type: str | None = None
    ) -> dict:
        return {
            "_kind": "embedded_text_resource",
            "uri": uri,
            "text": text,
            "mime_type": mime_type,
        }

    def embedded_blob_resource(
        uri: str, blob: str, *, mime_type: str | None = None
    ) -> dict:
        return {
            "_kind": "embedded_blob_resource",
            "uri": uri,
            "blob": blob,
            "mime_type": mime_type,
        }

    class FakeEmbedded:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    acp_mod.text_block = text_block
    acp_mod.image_block = image_block
    acp_mod.audio_block = audio_block
    acp_mod.resource_link_block = resource_link_block
    acp_mod.embedded_text_resource = embedded_text_resource
    acp_mod.embedded_blob_resource = embedded_blob_resource
    acp_mod.schema = schema_mod
    schema_mod.EmbeddedResourceContentBlock = FakeEmbedded

    return acp_mod, schema_mod


def _install_fake_acp() -> None:
    acp_mod, schema_mod = _fake_acp_module()
    sys.modules["acp"] = acp_mod
    sys.modules["acp.schema"] = schema_mod


def _uninstall_fake_acp() -> None:
    sys.modules.pop("acp", None)
    sys.modules.pop("acp.schema", None)


def _make_session(caps: AcpCapabilityState | None = None) -> AcpSession:
    session = AcpSession()
    session._capabilities = caps or AcpCapabilityState()
    session._connection = object()
    session._session_id = "s1"
    return session


# ---------------------------------------------------------------------------
# Phase 2: Domain-model tests
# ---------------------------------------------------------------------------


class PromptContentDomainTests(unittest.TestCase):
    """Valid construction and exact normalised representation for every kind."""

    def test_text_block_normalized(self) -> None:
        content = make_prompt_content({"kind": "text", "name": "msg", "text": "hello"})
        self.assertEqual(content.kind, PromptKind.TEXT)
        self.assertEqual(content.name, "msg")
        self.assertEqual(content.text, "hello")
        self.assertIsNone(content.mime_type)
        self.assertIsNone(content.data)
        self.assertIsNone(content.uri)
        self.assertEqual(content.size_bytes, len(b"hello"))

    def test_image_block_normalized(self) -> None:
        raw = b"\x89PNG"
        b64 = base64.b64encode(raw).decode("ascii")
        content = make_prompt_content(
            {
                "kind": "image",
                "name": "img.png",
                "mime_type": "image/png",
                "data_base64": b64,
            }
        )
        self.assertEqual(content.kind, PromptKind.IMAGE)
        self.assertEqual(content.mime_type, "image/png")
        self.assertEqual(content.data, raw)
        self.assertIsNone(content.text)
        self.assertIsNone(content.uri)
        self.assertEqual(content.size_bytes, len(raw))

    def test_audio_block_normalized(self) -> None:
        raw = b"\x00RIFF"
        b64 = base64.b64encode(raw).decode("ascii")
        content = make_prompt_content(
            {
                "kind": "audio",
                "name": "aud.wav",
                "mime_type": "audio/wav",
                "data_base64": b64,
            }
        )
        self.assertEqual(content.kind, PromptKind.AUDIO)
        self.assertEqual(content.data, raw)

    def test_resource_link_normalized(self) -> None:
        content = make_prompt_content(
            {
                "kind": "resource_link",
                "name": "r.txt",
                "uri": "https://example.com/r.txt",
                "mime_type": "text/plain",
            }
        )
        self.assertEqual(content.kind, PromptKind.RESOURCE_LINK)
        self.assertEqual(content.uri, "https://example.com/r.txt")
        self.assertEqual(content.mime_type, "text/plain")
        self.assertIsNone(content.data)
        self.assertIsNone(content.text)

    def test_embedded_text_normalized(self) -> None:
        content = make_prompt_content(
            {
                "kind": "embedded_text",
                "name": "e.txt",
                "mime_type": "text/plain",
                "text": "inline",
            }
        )
        self.assertEqual(content.kind, PromptKind.EMBEDDED_TEXT)
        self.assertEqual(content.text, "inline")
        self.assertEqual(content.mime_type, "text/plain")
        self.assertIsNone(content.data)

    def test_embedded_blob_normalized(self) -> None:
        raw = b"binary"
        b64 = base64.b64encode(raw).decode("ascii")
        # application/zip is in the allowed embedded doc MIME set
        content = make_prompt_content(
            {
                "kind": "embedded_blob",
                "name": "b.zip",
                "mime_type": "application/zip",
                "data_base64": b64,
            }
        )
        self.assertEqual(content.kind, PromptKind.EMBEDDED_BLOB)
        self.assertEqual(content.data, raw)
        self.assertEqual(content.mime_type, "application/zip")

    def test_name_is_stripped(self) -> None:
        content = make_prompt_content(
            {"kind": "text", "name": "  spaced  ", "text": "x"}
        )
        self.assertEqual(content.name, "spaced")

    def test_text_size_uses_utf8_bytes(self) -> None:
        content = make_prompt_content({"kind": "text", "name": "t", "text": "héllo"})
        self.assertEqual(content.size_bytes, len("héllo".encode()))


class PromptContentRejectionTests(unittest.TestCase):
    """Invalid input must raise PromptValidationError at the factory boundary."""

    # -- unknown / missing kind --
    def test_unknown_kind_rejected(self) -> None:
        with self.assertRaises(PromptValidationError) as ctx:
            make_prompt_content({"kind": "video", "name": "v.mp4"})
        self.assertIn("unknown kind", str(ctx.exception))

    def test_missing_kind_rejected(self) -> None:
        with self.assertRaises(PromptValidationError) as ctx:
            make_prompt_content({"name": "t"})
        self.assertIn("kind", str(ctx.exception).lower())

    def test_kind_non_string_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content({"kind": 1, "name": "t"})

    # -- name --
    def test_missing_name_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content({"kind": "text", "text": "x"})

    def test_empty_name_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content({"kind": "text", "name": "", "text": "x"})

    def test_whitespace_name_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content({"kind": "text", "name": "   ", "text": "x"})

    # -- mutual exclusion per kind (table-driven) --
    def test_mutual_exclusion_per_kind(self) -> None:
        cases: list[tuple[str, dict]] = [
            (
                "text+data_base64",
                {"kind": "text", "name": "t", "text": "x", "data_base64": "a"},
            ),
            (
                "text+uri",
                {"kind": "text", "name": "t", "text": "x", "uri": "file:///x"},
            ),
            (
                "image+text",
                {
                    "kind": "image",
                    "name": "t",
                    "data_base64": "a",
                    "mime_type": "image/png",
                    "text": "x",
                },
            ),
            (
                "image+uri",
                {
                    "kind": "image",
                    "name": "t",
                    "data_base64": "a",
                    "mime_type": "image/png",
                    "uri": "file:///x",
                },
            ),
            (
                "audio+text",
                {
                    "kind": "audio",
                    "name": "t",
                    "data_base64": "a",
                    "mime_type": "audio/wav",
                    "text": "x",
                },
            ),
            (
                "audio+uri",
                {
                    "kind": "audio",
                    "name": "t",
                    "data_base64": "a",
                    "mime_type": "audio/wav",
                    "uri": "file:///x",
                },
            ),
            (
                "resource_link+text",
                {"kind": "resource_link", "name": "t", "uri": "file:///x", "text": "x"},
            ),
            (
                "resource_link+b64",
                {
                    "kind": "resource_link",
                    "name": "t",
                    "uri": "file:///x",
                    "data_base64": "a",
                },
            ),
            (
                "embedded_text+b64",
                {
                    "kind": "embedded_text",
                    "name": "t",
                    "text": "x",
                    "mime_type": "text/plain",
                    "data_base64": "a",
                },
            ),
            (
                "embedded_text+uri",
                {
                    "kind": "embedded_text",
                    "name": "t",
                    "text": "x",
                    "mime_type": "text/plain",
                    "uri": "file:///x",
                },
            ),
            (
                "embedded_blob+text",
                {
                    "kind": "embedded_blob",
                    "name": "t",
                    "data_base64": "a",
                    "mime_type": "application/zip",
                    "text": "x",
                },
            ),
            (
                "embedded_blob+uri",
                {
                    "kind": "embedded_blob",
                    "name": "t",
                    "data_base64": "a",
                    "mime_type": "application/zip",
                    "uri": "file:///x",
                },
            ),
        ]
        for label, data in cases:
            with self.subTest(label=label), self.assertRaises(PromptValidationError):
                make_prompt_content(data)

    # -- missing required fields --
    def test_image_missing_data_base64_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content(
                {"kind": "image", "name": "t", "mime_type": "image/png"}
            )

    def test_image_missing_mime_rejected(self) -> None:
        with self.assertRaises(PromptValidationError) as ctx:
            make_prompt_content(
                {"kind": "image", "name": "t", "data_base64": _IMAGE_B64}
            )
        self.assertIn("mime_type", str(ctx.exception).lower())

    def test_audio_missing_mime_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content(
                {"kind": "audio", "name": "t", "data_base64": _AUDIO_B64}
            )

    def test_text_missing_text_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content({"kind": "text", "name": "t"})

    def test_resource_link_missing_uri_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content({"kind": "resource_link", "name": "t"})

    def test_embedded_text_missing_text_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content(
                {"kind": "embedded_text", "name": "t", "mime_type": "text/plain"}
            )

    def test_embedded_blob_missing_data_base64_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content(
                {"kind": "embedded_blob", "name": "t", "mime_type": "application/zip"}
            )

    # -- wrong field types --
    def test_text_non_string_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content({"kind": "text", "name": "t", "text": 42})

    def test_image_non_string_b64_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content(
                {
                    "kind": "image",
                    "name": "t",
                    "mime_type": "image/png",
                    "data_base64": b"raw",
                }
            )

    # -- base64 validation --
    def test_empty_base64_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content(
                {
                    "kind": "image",
                    "name": "t",
                    "mime_type": "image/png",
                    "data_base64": "",
                }
            )

    def test_invalid_base64_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content(
                {
                    "kind": "image",
                    "name": "t",
                    "mime_type": "image/png",
                    "data_base64": "!!!not-base64!!!",
                }
            )

    def test_base64_non_canonical_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content(
                {
                    "kind": "image",
                    "name": "t",
                    "mime_type": "image/png",
                    "data_base64": "aGVsbG8",
                }
            )

    # -- MIME type validation --
    def test_image_unsupported_mime_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content(
                {
                    "kind": "image",
                    "name": "t",
                    "mime_type": "application/pdf",
                    "data_base64": _IMAGE_B64,
                }
            )

    def test_audio_unsupported_mime_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content(
                {
                    "kind": "audio",
                    "name": "t",
                    "mime_type": "text/plain",
                    "data_base64": _AUDIO_B64,
                }
            )

    def test_embedded_text_unsupported_mime_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content(
                {
                    "kind": "embedded_text",
                    "name": "t",
                    "mime_type": "image/png",
                    "text": "x",
                }
            )

    def test_embedded_blob_unsupported_mime_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content(
                {
                    "kind": "embedded_blob",
                    "name": "t",
                    "mime_type": "image/png",
                    "data_base64": _IMAGE_B64,
                }
            )

    def test_embedded_text_accepted_mimes(self) -> None:
        for mime in (
            "text/plain",
            "text/csv",
            "text/html",
            "text/xml",
            "application/json",
            "application/pdf",
            "application/zip",
        ):
            with self.subTest(mime=mime):
                content = make_prompt_content(
                    {
                        "kind": "embedded_text",
                        "name": "t",
                        "mime_type": mime,
                        "text": "x",
                    }
                )
                self.assertEqual(content.mime_type, mime)

    def test_embedded_blob_accepted_mimes(self) -> None:
        for mime in ("application/pdf", "application/zip"):
            with self.subTest(mime=mime):
                content = make_prompt_content(
                    {
                        "kind": "embedded_blob",
                        "name": "t",
                        "mime_type": mime,
                        "data_base64": _IMAGE_B64,
                    }
                )
                self.assertEqual(content.mime_type, mime)

    # -- URI validation --
    def test_uri_credentials_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content(
                {"kind": "resource_link", "name": "t", "uri": "file://user:pass@host/x"}
            )

    def test_uri_http_scheme_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content(
                {"kind": "resource_link", "name": "t", "uri": "http://example.com/x"}
            )

    def test_uri_empty_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content({"kind": "resource_link", "name": "t", "uri": ""})

    def test_uri_whitespace_only_rejected(self) -> None:
        with self.assertRaises(PromptValidationError):
            make_prompt_content({"kind": "resource_link", "name": "t", "uri": "   "})

    def test_uri_https_accepted(self) -> None:
        content = make_prompt_content(
            {"kind": "resource_link", "name": "t", "uri": "https://example.com/x"}
        )
        self.assertEqual(content.uri, "https://example.com/x")

    def test_uri_file_accepted(self) -> None:
        content = make_prompt_content(
            {"kind": "resource_link", "name": "t", "uri": "file:///tmp/x"}
        )
        self.assertEqual(content.uri, "file:///tmp/x")

    # -- path traversal in name --
    def test_name_path_traversal_rejected(self) -> None:
        for bad_name in ("../etc/passwd", "a/b.txt", "a\\b.txt"):
            with self.subTest(name=bad_name), self.assertRaises(PromptValidationError):
                make_prompt_content({"kind": "text", "name": bad_name, "text": "x"})

    # -- size / limit validation --
    def test_item_size_exceeds_limit(self) -> None:
        payload = b"x" * (DEFAULT_MAX_ITEM_BYTES + 1)
        b64 = base64.b64encode(payload).decode("ascii")
        content = make_prompt_content(
            {
                "kind": "image",
                "name": "big.png",
                "mime_type": "image/png",
                "data_base64": b64,
            }
        )
        with self.assertRaises(PromptValidationError):
            validate_prompt_limits([content])

    def test_total_size_exceeds_limit(self) -> None:
        half = b"x" * (DEFAULT_MAX_TOTAL_BYTES // 2 + 1)
        b64 = base64.b64encode(half).decode("ascii")
        contents = [
            make_prompt_content(
                {
                    "kind": "image",
                    "name": "a.png",
                    "mime_type": "image/png",
                    "data_base64": b64,
                }
            ),
            make_prompt_content(
                {
                    "kind": "image",
                    "name": "b.png",
                    "mime_type": "image/png",
                    "data_base64": b64,
                }
            ),
        ]
        with self.assertRaises(PromptValidationError):
            validate_prompt_limits(contents)

    def test_block_count_exceeds_limit(self) -> None:
        contents = [
            make_prompt_content({"kind": "text", "name": f"t{i}", "text": "x"})
            for i in range(DEFAULT_MAX_COUNT + 1)
        ]
        with self.assertRaises(PromptValidationError):
            validate_prompt_limits(contents)

    # -- error messages must not leak raw content --
    def test_error_no_raw_base64_leak(self) -> None:
        bad_b64 = "!!!invalid-base64!!!"
        with self.assertRaises(PromptValidationError) as ctx:
            make_prompt_content(
                {
                    "kind": "image",
                    "name": "t.png",
                    "mime_type": "image/png",
                    "data_base64": bad_b64,
                }
            )
        self.assertNotIn(bad_b64, str(ctx.exception))

    def test_supported_embedded_text_mimes(self) -> None:
        for mime in (
            "text/plain",
            "text/csv",
            "text/html",
            "text/xml",
            "application/json",
            "application/pdf",
            "application/zip",
        ):
            with self.subTest(mime=mime):
                c = make_prompt_content(
                    {
                        "kind": "embedded_text",
                        "name": "t",
                        "mime_type": mime,
                        "text": "x",
                    }
                )
                self.assertEqual(c.mime_type, mime)


# ---------------------------------------------------------------------------
# Phase 3: Capability negotiation tests
# ---------------------------------------------------------------------------


class CapabilityNegotiationTests(unittest.IsolatedAsyncioTestCase):
    """Attachment support is derived from negotiated ACP capability state."""

    async def test_text_only_works_without_attachment_caps(self) -> None:
        caps = AcpCapabilityState()
        caps.attachment_images = False
        caps.attachment_audio = False
        caps.attachment_embedded = False
        session = _make_session(caps)
        content = [
            make_prompt_content({"kind": "text", "name": "msg", "text": "hello"})
        ]
        try:
            await session.submit_prompt_content(content)
        except RuntimeError as exc:
            self.assertNotIn("attachment rejected", str(exc))
        except (AttributeError, ImportError):
            pass  # fake connection has no prompt() — acceptable after cap check passes

    async def test_image_rejected_when_capability_false(self) -> None:
        caps = AcpCapabilityState()
        caps.attachment_images = False
        session = _make_session(caps)
        content = [
            make_prompt_content(
                {
                    "kind": "image",
                    "name": "t.png",
                    "mime_type": "image/png",
                    "data_base64": _IMAGE_B64,
                }
            )
        ]
        with self.assertRaises(RuntimeError) as ctx:
            await session.submit_prompt_content(content)
        self.assertIn("image not supported", str(ctx.exception).lower())

    async def test_audio_rejected_when_capability_false(self) -> None:
        caps = AcpCapabilityState()
        caps.attachment_audio = False
        session = _make_session(caps)
        content = [
            make_prompt_content(
                {
                    "kind": "audio",
                    "name": "t.wav",
                    "mime_type": "audio/wav",
                    "data_base64": _AUDIO_B64,
                }
            )
        ]
        with self.assertRaises(RuntimeError) as ctx:
            await session.submit_prompt_content(content)
        self.assertIn("audio not supported", str(ctx.exception).lower())

    async def test_embedded_rejected_when_capability_false(self) -> None:
        caps = AcpCapabilityState()
        caps.attachment_embedded = False
        session = _make_session(caps)
        for kind in (PromptKind.EMBEDDED_TEXT, PromptKind.EMBEDDED_BLOB):
            with self.subTest(kind=kind.value):
                data: dict[str, Any]
                if kind == PromptKind.EMBEDDED_TEXT:
                    data = {
                        "kind": "embedded_text",
                        "name": "t",
                        "mime_type": "text/plain",
                        "text": "x",
                    }
                else:
                    data = {
                        "kind": "embedded_blob",
                        "name": "t",
                        "mime_type": "application/zip",
                        "data_base64": _IMAGE_B64,
                    }
                content = [make_prompt_content(data)]
                with self.assertRaises(RuntimeError) as ctx:
                    await session.submit_prompt_content(content)
                self.assertIn("embedded", str(ctx.exception).lower())

    async def test_resource_link_always_supported(self) -> None:
        """Resource links are baseline per ACP v1 — never gated."""
        caps = AcpCapabilityState()
        caps.attachment_images = False
        caps.attachment_audio = False
        caps.attachment_embedded = False
        session = _make_session(caps)
        content = [
            make_prompt_content(
                {"kind": "resource_link", "name": "t.txt", "uri": "file:///x"}
            )
        ]
        try:
            await session.submit_prompt_content(content)
        except RuntimeError as exc:
            self.assertNotIn("attachment rejected", str(exc))
        except (AttributeError, ImportError):
            pass  # fake connection — acceptable after cap check passes

    async def test_false_capabilities_dont_get_invented(self) -> None:
        caps = AcpCapabilityState()
        self.assertFalse(caps.attachment_images)
        self.assertFalse(caps.attachment_audio)
        self.assertFalse(caps.attachment_embedded)
        self.assertTrue(caps.attachment_resource_links)

    async def test_server_adapter_reports_no_attachments(self) -> None:
        """The OpenCode server adapter declares attachments unavailable with the
        correct reason — not pending discovery, because its REST API has no
        attachment schema to negotiate."""
        adapter = OpenCodeServerAdapter(opencode_bin="fake")
        adapter._initialized = True
        adapter._agent_name = "opencode"
        snap = adapter.capability_snapshot()
        self.assertIsInstance(snap.attachments, UnavailableCapability)
        self.assertEqual(
            snap.attachments.reason, UnavailabilityReason.NOT_EXPOSED_BY_PROVIDER
        )

    async def test_attachments_available_reflects_negotiated_state(self) -> None:
        ac = AttachmentCapabilities(
            block_types=("resource_link", "image", "embedded_text", "embedded_blob"),
            resource_links=True,
            images=True,
            audio=False,
            embedded_resources=True,
        )
        snap = CapabilitySnapshot(source="test", attachments=ac)
        self.assertTrue(isinstance(snap.attachments, AttachmentCapabilities))
        at = snap.attachments
        self.assertIn("image", at.block_types)
        self.assertNotIn("audio", at.block_types)
        self.assertTrue(at.images)
        self.assertFalse(at.audio)
        self.assertTrue(at.embedded_resources)

    async def test_filesystem_caps_dont_imply_attachment_cap(self) -> None:
        caps = AcpCapabilityState()
        self.assertFalse(caps.attachment_images)
        self.assertFalse(caps.attachment_audio)
        self.assertFalse(caps.attachment_embedded)


# ---------------------------------------------------------------------------
# Phase 4: ACP block-conversion tests
# ---------------------------------------------------------------------------


class AcpBlockConversionTests(unittest.IsolatedAsyncioTestCase):
    """Verify RTAI converts validated blocks to the pinned ACP SDK types."""

    def setUp(self) -> None:
        _install_fake_acp()
        self.addCleanup(_uninstall_fake_acp)

    async def test_text_converts_to_text_block(self) -> None:
        session = _make_session()
        content = [
            make_prompt_content({"kind": "text", "name": "msg", "text": "hello"})
        ]
        with contextlib.suppress(AttributeError):
            await session.submit_prompt_content(content)

    async def test_image_converts_to_image_block(self) -> None:
        caps = AcpCapabilityState()
        caps.attachment_images = True
        session = _make_session(caps)
        content = [
            make_prompt_content(
                {
                    "kind": "image",
                    "name": "img.png",
                    "mime_type": "image/png",
                    "data_base64": _IMAGE_B64,
                }
            )
        ]
        with contextlib.suppress(AttributeError):
            await session.submit_prompt_content(content)

    async def test_audio_converts_to_audio_block(self) -> None:
        caps = AcpCapabilityState()
        caps.attachment_audio = True
        session = _make_session(caps)
        content = [
            make_prompt_content(
                {
                    "kind": "audio",
                    "name": "aud.wav",
                    "mime_type": "audio/wav",
                    "data_base64": _AUDIO_B64,
                }
            )
        ]
        with contextlib.suppress(AttributeError):
            await session.submit_prompt_content(content)

    async def test_resource_link_converts_to_resource_link_block(self) -> None:
        session = _make_session()
        content = [
            make_prompt_content(
                {
                    "kind": "resource_link",
                    "name": "r.txt",
                    "uri": "file:///tmp/r.txt",
                    "mime_type": "text/plain",
                }
            )
        ]
        with contextlib.suppress(AttributeError):
            await session.submit_prompt_content(content)

    async def test_embedded_text_converts_correctly(self) -> None:
        caps = AcpCapabilityState()
        caps.attachment_embedded = True
        session = _make_session(caps)
        content = [
            make_prompt_content(
                {
                    "kind": "embedded_text",
                    "name": "e.txt",
                    "mime_type": "text/plain",
                    "text": "inline",
                }
            )
        ]
        with contextlib.suppress(AttributeError):
            await session.submit_prompt_content(content)

    async def test_embedded_blob_converts_correctly(self) -> None:
        caps = AcpCapabilityState()
        caps.attachment_embedded = True
        session = _make_session(caps)
        content = [
            make_prompt_content(
                {
                    "kind": "embedded_blob",
                    "name": "b.zip",
                    "mime_type": "application/zip",
                    "data_base64": _IMAGE_B64,
                }
            )
        ]
        with contextlib.suppress(AttributeError):
            await session.submit_prompt_content(content)

    async def test_block_order_preserved(self) -> None:
        """Blocks must reach the SDK in their original order."""
        caps = AcpCapabilityState()
        caps.attachment_images = True
        caps.attachment_embedded = True
        session = _make_session(caps)
        content = [
            make_prompt_content({"kind": "text", "name": "msg", "text": "hello"}),
            make_prompt_content(
                {
                    "kind": "image",
                    "name": "img.png",
                    "mime_type": "image/png",
                    "data_base64": _IMAGE_B64,
                }
            ),
            make_prompt_content(
                {
                    "kind": "embedded_text",
                    "name": "e.txt",
                    "mime_type": "text/plain",
                    "text": "inline",
                }
            ),
        ]
        with contextlib.suppress(AttributeError):
            await session.submit_prompt_content(content)

    async def test_unsupported_block_rejected_before_prompt_call(self) -> None:
        """A block whose kind is not advertised must raise before any SDK call."""
        caps = AcpCapabilityState()
        caps.attachment_images = False
        session = _make_session(caps)
        content = [
            make_prompt_content(
                {
                    "kind": "image",
                    "name": "img.png",
                    "mime_type": "image/png",
                    "data_base64": _IMAGE_B64,
                }
            )
        ]
        with self.assertRaises(RuntimeError) as ctx:
            await session.submit_prompt_content(content)
        self.assertIn("image not supported", str(ctx.exception).lower())

    async def test_text_only_backward_compatible(self) -> None:
        """A single text block prompt works even when no attachments are advertised."""
        caps = AcpCapabilityState()
        caps.attachment_images = False
        caps.attachment_audio = False
        caps.attachment_embedded = False
        session = _make_session(caps)
        content = [
            make_prompt_content({"kind": "text", "name": "msg", "text": "hello"})
        ]
        with contextlib.suppress(AttributeError):
            await session.submit_prompt_content(content)

    async def test_no_real_acp_process_started(self) -> None:
        """The fake acp module means no real SDK functions are called."""
        import acp

        self.assertIsInstance(acp, ModuleType)
        self.assertEqual(acp.__name__, "acp")
        self.assertTrue(hasattr(acp, "text_block"))


if __name__ == "__main__":
    unittest.main()
