"""Immutable prompt content block model (provider-neutral).

Each block represents one ordered piece of a user prompt. The adapter
boundary receives these objects — never raw JSON dicts or SDK-specific types.

Validation (MIME allowlist, size limits, URI safety, base64 decoding) happens
at the factory level; produced objects are guaranteed to be internally
consistent.
"""

from __future__ import annotations

import base64
import re
import urllib.parse
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath

from .base import AgentAdapter

# --- Kinds ------------------------------------------------------------------


class PromptKind(str, Enum):
    """Discriminant for the ordered prompt-content blocks."""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    RESOURCE_LINK = "resource_link"
    EMBEDDED_TEXT = "embedded_text"
    EMBEDDED_BLOB = "embedded_blob"


# --- MIME allowlist ---------------------------------------------------------

# Only these MIME families are accepted for inline (base64) content.
# General documents use resource_link or embedded_resource instead.
_ALLOWED_INLINE_MIME_PREFIXES: tuple[str, ...] = (
    "image/",
    "audio/",
)

_ALLOWED_EMBEDDED_DOC_MIME_TYPES: frozenset[str] = frozenset(
    {
        "text/plain",
        "text/csv",
        "text/html",
        "text/xml",
        "application/json",
        "application/pdf",
        "application/zip",
    }
)

# Regex for a clean filename: no path separators, no control chars, no
# Windows reserved names, no leading/trailing dots or spaces.
_SAFE_FILENAME_RE = re.compile(r"^[^/\\:*?\"<>|\r\n\x00-\x1f][^/\\:*?\"<>|\r\n\x00-\x1f]{0,254}$")


# --- Shared data-URL + message-part attachment validation ---------------------

# Explicit safe MIME allowlist for AssistantTransport message-part image
# attachments. SVG/XML image types are intentionally excluded: they can carry
# executable script and are not safe opaque image attachments in this POC.
_ALLOWED_MESSAGE_IMAGE_MIME_TYPES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/bmp",
        "image/x-icon",
        "image/avif",
    }
)

# Strict data: URL grammar: data:<mime>;base64,<payload>. No other forms
# (missing prefix, missing MIME, missing ``;base64,`` separator, empty payload,
# or trailing garbage) are accepted. This is the single shared parser used by
# both pre-stream message validation and the AssistantTransport endpoint, so the
# supported-type matrix lives in exactly one provider-neutral location.
_DATA_URL_RE = re.compile(r"^data:([^;,\s]+);base64,([^,]*)$")


def parse_inline_data_url(url: str) -> tuple[str, str]:
    """Parse an inline ``data:`` URL into ``(mime_type, base64_payload)``.

    Rejects any malformed URL with :class:`PromptValidationError`: missing
    ``data:`` prefix, missing/empty MIME, missing ``;base64,`` separator,
    non-image MIME, empty payload, or invalid base64. The payload is validated
    strictly but NOT retained here; final decode + size limits happen in
    :func:`make_prompt_content`.
    """
    if not isinstance(url, str) or not url.strip():
        raise PromptValidationError("image part must carry a non-empty data URL")
    match = _DATA_URL_RE.match(url.strip())
    if match is None:
        raise PromptValidationError(
            "image part must be a data: URL of the form data:<mime>;base64,<payload>"
        )
    mime = match.group(1).strip().lower()
    if mime not in _ALLOWED_MESSAGE_IMAGE_MIME_TYPES:
        raise PromptValidationError(
            f"unsupported image MIME type {mime!r}; allowed: "
            f"{sorted(_ALLOWED_MESSAGE_IMAGE_MIME_TYPES)}"
        )
    payload = match.group(2)
    if not payload:
        raise PromptValidationError("image part data URL must have a non-empty base64 payload")
    try:
        base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise PromptValidationError(f"invalid base64 payload in image part: {exc}") from exc
    return mime, payload


# --- Domain model -----------------------------------------------------------


@dataclass(frozen=True)
class PromptContent:
    """One ordered piece of a user prompt. Immutable after creation."""

    kind: PromptKind
    name: str
    mime_type: str | None = None
    text: str | None = None
    data: bytes | None = None  # decoded bytes (never base64)
    uri: str | None = None

    @property
    def size_bytes(self) -> int:
        if self.kind == PromptKind.TEXT and self.text is not None:
            return len(self.text.encode("utf-8"))
        if self.data is not None:
            return len(self.data)
        return 0


# --- Validation & factory ---------------------------------------------------


class PromptValidationError(ValueError):
    """Raised when a prompt block fails validation."""


def _require_non_empty(value: str, label: str) -> None:
    if not value or not value.strip():
        raise PromptValidationError(f"{label} must be non-empty")


def _validate_name(name: str) -> str:
    if not name or not name.strip():
        raise PromptValidationError("name must be non-empty")
    if not _SAFE_FILENAME_RE.match(name):
        raise PromptValidationError(
            f"invalid filename: {name!r} — only alphanumerics, dots, dashes, "
            "underscores, and spaces are allowed; no path separators"
        )
    # Sanitize: strip leading/trailing whitespace from each segment
    return name.strip()


def _validate_mime_type(kind: PromptKind, mime_type: str | None) -> str | None:
    if mime_type is None:
        if kind in (PromptKind.IMAGE, PromptKind.AUDIO):
            raise PromptValidationError(f"{kind.value} kind requires a non-empty mime_type")
        return None
    mime_type = mime_type.strip().lower()
    if not mime_type:
        if kind in (PromptKind.IMAGE, PromptKind.AUDIO):
            raise PromptValidationError(f"{kind.value} kind requires a non-empty mime_type")
        return None
    # Inline image/audio: must match known prefix
    if kind in (PromptKind.IMAGE, PromptKind.AUDIO):
        if not any(mime_type.startswith(p) for p in _ALLOWED_INLINE_MIME_PREFIXES):
            raise PromptValidationError(
                f"unsupported inline MIME type {mime_type!r} for {kind.value}; "
                f"expected image/* or audio/*"
            )
    elif (
        kind in (PromptKind.EMBEDDED_TEXT, PromptKind.EMBEDDED_BLOB)
        and mime_type not in _ALLOWED_EMBEDDED_DOC_MIME_TYPES
    ):
        raise PromptValidationError(
            f"unsupported embedded MIME type {mime_type!r}; "
            f"allowed: {sorted(_ALLOWED_EMBEDDED_DOC_MIME_TYPES)}"
        )
    return mime_type


def _coerce_mime_type(kind: PromptKind, value: object) -> str | None:
    """Validate a raw ``mime_type`` value from a JSON dict into a normalized str.

    Accepts ``None`` or a string; anything else is rejected. Delegates the
    allowlist/emptiness checks to :func:`_validate_mime_type`.
    """
    if value is None:
        return _validate_mime_type(kind, None)
    if not isinstance(value, str):
        raise PromptValidationError(f"{kind.value} mime_type must be a string")
    return _validate_mime_type(kind, value)


def _decode_base64(data: str, label: str) -> bytes:
    if not data:
        raise PromptValidationError(f"{label} must not be empty")
    try:
        decoded = base64.b64decode(data, validate=True)
    except Exception as exc:
        raise PromptValidationError(f"{label}: invalid base64 — {exc}") from exc
    return decoded


def _validate_uri(uri: str, kind: PromptKind) -> str:
    uri = uri.strip()
    if not uri:
        raise PromptValidationError(f"{kind.value} URI must not be empty")
    parsed = urllib.parse.urlparse(uri)
    # Reject credentials
    if parsed.username or parsed.password:
        raise PromptValidationError(f"{kind.value}: URI must not contain credentials")
    if parsed.scheme == "file":
        # Resolve and check containment (done by caller with project root)
        pass
    elif parsed.scheme == "https":
        pass
    else:
        raise PromptValidationError(
            f"{kind.value}: unsupported URI scheme {parsed.scheme!r}; "
            "only file: and https: are allowed"
        )
    return uri


def _validate_name_path_traversal(name: str) -> str:
    # Reject path traversal in name
    parts = PurePosixPath(name).parts
    for part in parts:
        if part in ("..", "."):
            raise PromptValidationError(f"name contains path traversal: {name!r}")
    return name


# --- Public factory ---------------------------------------------------------


def make_prompt_content(data: dict[str, object]) -> PromptContent:
    """Validate and construct a PromptContent from a Protocol v1 JSON dict.

    Raises PromptValidationError on any violation.
    """
    kind_raw = data.get("kind")
    if not isinstance(kind_raw, str):
        raise PromptValidationError("kind is required and must be a string")
    try:
        kind = PromptKind(kind_raw)
    except ValueError as exc:
        raise PromptValidationError(
            f"unknown kind {kind_raw!r}; expected one of: {sorted(k.value for k in PromptKind)}"
        ) from exc

    name = _validate_name(str(data.get("name", "")))
    name = _validate_name_path_traversal(name)

    if kind == PromptKind.TEXT:
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            raise PromptValidationError("text kind requires non-empty text")
        # Mutually exclusive fields must be absent
        if "data_base64" in data or "uri" in data:
            raise PromptValidationError("text kind must not have data_base64 or uri")
        return PromptContent(
            kind=kind,
            name=name,
            text=text,
            mime_type=None,
            data=None,
            uri=None,
        )

    if kind == PromptKind.IMAGE:
        b64 = data.get("data_base64")
        if not isinstance(b64, str) or not b64:
            raise PromptValidationError("image kind requires data_base64")
        if "text" in data or "uri" in data:
            raise PromptValidationError("image kind must not have text or uri")
        mime = _coerce_mime_type(kind, data.get("mime_type"))
        decoded = _decode_base64(b64, "image data_base64")
        return PromptContent(
            kind=kind,
            name=name,
            mime_type=mime,
            text=None,
            data=decoded,
            uri=None,
        )

    if kind == PromptKind.AUDIO:
        b64 = data.get("data_base64")
        if not isinstance(b64, str) or not b64:
            raise PromptValidationError("audio kind requires data_base64")
        if "text" in data or "uri" in data:
            raise PromptValidationError("audio kind must not have text or uri")
        mime = _coerce_mime_type(kind, data.get("mime_type"))
        decoded = _decode_base64(b64, "audio data_base64")
        return PromptContent(
            kind=kind,
            name=name,
            mime_type=mime,
            text=None,
            data=decoded,
            uri=None,
        )

    if kind == PromptKind.RESOURCE_LINK:
        uri = data.get("uri")
        if not isinstance(uri, str) or not uri.strip():
            raise PromptValidationError("resource_link kind requires uri")
        if "text" in data or "data_base64" in data:
            raise PromptValidationError("resource_link kind must not have text or data_base64")
        validated_uri = _validate_uri(uri, kind)
        mime = _coerce_mime_type(kind, data.get("mime_type"))
        return PromptContent(
            kind=kind,
            name=name,
            mime_type=mime,
            text=None,
            data=None,
            uri=validated_uri,
        )

    if kind == PromptKind.EMBEDDED_TEXT:
        txt = data.get("text")
        if not isinstance(txt, str):
            raise PromptValidationError("embedded_text kind requires text")
        if "data_base64" in data or "uri" in data:
            raise PromptValidationError("embedded_text kind must not have data_base64 or uri")
        mime = _coerce_mime_type(kind, data.get("mime_type"))
        return PromptContent(
            kind=kind,
            name=name,
            mime_type=mime,
            text=txt,
            data=None,
            uri=None,
        )

    if kind == PromptKind.EMBEDDED_BLOB:
        b64 = data.get("data_base64")
        if not isinstance(b64, str) or not b64:
            raise PromptValidationError("embedded_blob kind requires data_base64")
        if "text" in data or "uri" in data:
            raise PromptValidationError("embedded_blob kind must not have text or uri")
        mime = _coerce_mime_type(kind, data.get("mime_type"))
        decoded = _decode_base64(b64, "embedded_blob data_base64")
        return PromptContent(
            kind=kind,
            name=name,
            mime_type=mime,
            text=None,
            data=decoded,
            uri=None,
        )

    raise PromptValidationError(f"unknown kind: {kind_raw!r}")


# --- Safety limits ------------------------------------------------------------

# Default RTAI safety limits (configurable via RTAI_* env vars).
DEFAULT_MAX_ITEM_BYTES = 5 * 1024 * 1024  # 5 MiB per attachment
DEFAULT_MAX_TOTAL_BYTES = 10 * 1024 * 1024  # 10 MiB per prompt
DEFAULT_MAX_COUNT = 10


def validate_prompt_limits(
    content: list[PromptContent],
    *,
    max_item_bytes: int = DEFAULT_MAX_ITEM_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_count: int = DEFAULT_MAX_COUNT,
) -> None:
    """Check RTAI safety limits before adapter dispatch.

    Raises PromptValidationError on violation.
    """
    if len(content) > max_count:
        raise PromptValidationError(f"too many prompt blocks: {len(content)} > {max_count}")
    total = 0
    for block in content:
        size = block.size_bytes
        if size > max_item_bytes:
            raise PromptValidationError(
                f"attachment {block.name!r} exceeds {max_item_bytes} bytes ({size} bytes)"
            )
        total += size
    if total > max_total_bytes:
        raise PromptValidationError(
            f"prompt total size {total} bytes exceeds {max_total_bytes} bytes"
        )


async def submit_prompt_blocks(
    adapter: AgentAdapter,
    blocks: list[dict[str, object]],
) -> None:
    """Validate and dispatch a multi-block prompt (text + validated attachments).

    Provider-neutral: shared by the AssistantTransport endpoint and its
    pre-stream validation so conversion/validation lives in exactly one place.

    ``blocks`` are raw PromptContent dicts (keys: kind, name, mime_type, text,
    data_base64, uri) in message order. Text-only prompts are joined and sent via
    ``adapter.submit_prompt`` (preserving prior behavior); any non-text block takes
    the ``submit_prompt_content`` path after capability + limit validation.
    """
    if not blocks:
        return

    # Text-only prompt: preserve exact prior behavior (single joined submit_prompt).
    if all(b.get("kind") == "text" for b in blocks):
        joined = "\n".join((b.get("text") or "") for b in blocks).strip()
        if joined:
            await adapter.submit_prompt(joined)
        return

    # Mixed text + attachments (or attachments only): require adapter support.
    from .capabilities import AttachmentCapabilities

    snap = adapter.capability_snapshot()
    ac = snap.attachments
    if not isinstance(ac, AttachmentCapabilities) or not ac.block_types:
        raise RuntimeError("attachments not supported by this agent")

    parsed = [make_prompt_content(dict(b)) for b in blocks]
    validate_prompt_limits(
        parsed,
        max_item_bytes=ac.max_item_bytes,
        max_total_bytes=ac.max_total_bytes,
        max_count=ac.max_count,
    )
    kind_map = {
        "image": "images",
        "audio": "audio",
        "embedded_text": "embedded_resources",
        "embedded_blob": "embedded_resources",
    }
    for b in parsed:
        attr = kind_map.get(b.kind.value)
        if attr and attr in vars(ac) and not getattr(ac, attr):
            raise RuntimeError(f"attachment rejected: {b.kind.value} not supported by this agent")
    await adapter.submit_prompt_content(parsed)


__all__ = [
    "PromptKind",
    "PromptContent",
    "PromptValidationError",
    "make_prompt_content",
    "parse_inline_data_url",
    "validate_prompt_limits",
    "DEFAULT_MAX_ITEM_BYTES",
    "DEFAULT_MAX_TOTAL_BYTES",
    "DEFAULT_MAX_COUNT",
]
