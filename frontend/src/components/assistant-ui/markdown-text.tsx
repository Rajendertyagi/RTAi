"use client";

import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import { memo, type FC, type TextMessagePartProps } from "react";
import { cn } from "@/lib/utils";

/**
 * Official MarkdownText Element (RTAI adaptation).
 *
 * The upstream registry `@assistant-ui/elements-markdown-text` bundles
 * `remark-gfm` plus a tooltip/code-copy header that depend on packages and
 * hooks absent from this project's pinned surface (`remark-gfm`,
 * `@/hooks/use-copy-to-clipboard`, `@/components/assistant-ui/tooltip-icon-button`,
 * `@/components/ui/tooltip`). This adaptation keeps the official contract — a
 * context-driven `TextMessagePartComponent` over the official
 * `MarkdownTextPrimitive` — and relies on the project's existing
 * `styles/markdown.css` for typography. Runtime behavior matches the prior
 * renderer; no new dependency is introduced.
 */
const MarkdownTextImpl: FC<Partial<TextMessagePartProps>> = () => {
  return (
    <div className="aui-md text-[0.9375rem] leading-relaxed text-surface-foreground overflow-wrap-break-word">
      <MarkdownTextPrimitive />
    </div>
  );
};

export const MarkdownText = memo(MarkdownTextImpl);
