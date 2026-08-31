"use client";

import { AuiIf, ChainOfThoughtPrimitive } from "@assistant-ui/react";
import { ChevronDown, ChevronUp } from "lucide-react";
import type { ReactNode } from "react";

interface ThinkingAccordionProps {
  children: ReactNode;
  /** Number of grouped parts inside this accordion */
  count?: number;
}

/**
 * Collapsible accordion for grouping reasoning + tool-call parts.
 *
 * Uses ChainOfThoughtPrimitive (the primitive-level API). The legacy
 * ChainOfThoughtPrimitive.Parts reads reasoning/tool context from the
 * nearest MessagePrimitive.Root. GroupedParts drives the same grouping
 * logic at a higher level; this component is the visual container.
 *
 * Shows the accordion only when there are children (empty groups are
 * filtered at the GroupedParts level, so this never renders an empty
 * accordion).
 */
export function ThinkingAccordion({
  children,
  count,
}: ThinkingAccordionProps) {
  return (
    <ChainOfThoughtPrimitive.Root className="my-1.5">
      <ChainOfThoughtPrimitive.AccordionTrigger className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-surface-foreground transition-colors hover:bg-interactive-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-interactive-focus-ring">
        <AuiIf condition={(s) => s.chainOfThought.collapsed}>
          <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
        </AuiIf>
        <AuiIf condition={(s) => !s.chainOfThought.collapsed}>
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        </AuiIf>
        <span className="flex-1 text-left font-medium text-sm">
          Thinking
          {count !== undefined && count > 0 && (
            <span className="ml-1.5 text-xs font-normal text-muted-foreground">
              ({count})
            </span>
          )}
        </span>
      </ChainOfThoughtPrimitive.AccordionTrigger>
      <AuiIf condition={(s) => !s.chainOfThought.collapsed}>
        <div className="rounded-b-lg border-x border-b border-interactive bg-surface-elevated px-3 py-2">
          {children}
        </div>
      </AuiIf>
    </ChainOfThoughtPrimitive.Root>
  );
}
