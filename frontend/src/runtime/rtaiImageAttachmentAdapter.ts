"use client";

import { SimpleImageAttachmentAdapter, type AttachmentAdapter } from "@assistant-ui/react";

/**
 * Narrow image-attachment adapter for the RTAI AssistantTransport frontend.
 *
 * The frozen backend (`backend/app/transport/assistant/models.py`) accepts only:
 *   image/png, image/jpeg, image/gif, image/webp, image/bmp, image/x-icon, image/avif
 * (enforced by `parse_inline_data_url` / the shared image-MIME allowlist).
 *
 * The pinned `SimpleImageAttachmentAdapter` hard-codes `accept = "image/*"` and performs
 * no MIME validation in `add()` / `send()` — it would forward unsupported image types
 * (e.g. svg/tiff/webp-animated) to the backend, which only rejects them with HTTP 400.
 * PART 3 requires rejecting unsupported MIME before sending, through the official
 * attachment error path, and not relying solely on the backend 400.
 *
 * This wrapper implements the official `AttachmentAdapter` contract exactly:
 *  - `accept` is the exact backend allowlist (also restricts the native file picker);
 *  - `add()` rejects unsupported MIME types by throwing (the official attachment error
 *    path surfaces a failed add);
 *  - `send()` / `remove()` delegate to one `SimpleImageAttachmentAdapter` instance, so
 *    the official data-URL conversion is reused and there is no second conversion
 *    pipeline, attachment store, or custom file reader.
 */
const RTAI_IMAGE_ACCEPT =
  "image/png,image/jpeg,image/gif,image/webp,image/bmp,image/x-icon,image/avif";

const RTAI_ALLOWED_MIME = new Set(RTAI_IMAGE_ACCEPT.split(","));

type PendingAttachment = Parameters<AttachmentAdapter["send"]>[0];

export class RtaiImageAttachmentAdapter implements AttachmentAdapter {
  public accept = RTAI_IMAGE_ACCEPT;
  private readonly inner = new SimpleImageAttachmentAdapter();

  public async add(state: { file: File }): Promise<PendingAttachment> {
    if (!RTAI_ALLOWED_MIME.has(state.file.type)) {
      throw new Error(
        `Unsupported image type "${state.file.type || "unknown"}". ` +
          "Allowed: PNG, JPEG, GIF, WebP, BMP, ICO, AVIF.",
      );
    }
    return this.inner.add(state);
  }

  public send(attachment: PendingAttachment) {
    return this.inner.send(attachment);
  }

  public remove() {
    return this.inner.remove();
  }
}
