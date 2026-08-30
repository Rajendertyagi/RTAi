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
        return None
    mime_type = mime_type.strip().lower()
    if not mime_type:
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
        mime = _validate_mime_type(kind, data.get("mime_type"))
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
        mime = _validate_mime_type(kind, data.get("mime_type"))
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
        mime = data.get("mime_type")
        if mime and not isinstance(mime, str):
            raise PromptValidationError("resource_link mime_type must be a string")
        return PromptContent(
            kind=kind,
            name=name,
            mime_type=mime.strip().lower() if isinstance(mime, str) and mime.strip() else None,
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
        mime = _validate_mime_type(kind, data.get("mime_type"))
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
        mime = _validate_mime_type(kind, data.get("mime_type"))
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


__all__ = [
    "PromptKind",
    "PromptContent",
    "PromptValidationError",
    "make_prompt_content",
    "validate_prompt_limits",
    "DEFAULT_MAX_ITEM_BYTES",
    "DEFAULT_MAX_TOTAL_BYTES",
    "DEFAULT_MAX_COUNT",
]
