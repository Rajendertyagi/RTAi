"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

interface ThinkingAccordionProps {
  children: ReactNode;
  /** Number of grouped parts inside this accordion */
  count?: number;
}

/**
 * Collapsible container for the official MessagePrimitive.GroupedParts
 * "group-chainOfThought" group.
 *
 * This is a plain React component: it owns only its own open/closed UI state
 * and renders `children` (the grouped reasoning + tool-call subtree) inside the
 * GroupedParts-provided part scope. It deliberately does NOT use the legacy
 * ChainOfThoughtPrimitive or read `s.chainOfThought`.
 *
 * The legacy ChainOfThoughtPrimitive.Root / `s.chainOfThought` scope is only
 * available when reasoning/tool parts are rendered through the legacy
 * components.ChainOfThought path. When those parts arrive through the new
 * GroupedParts path (as RTAI does), that scope is never created, so accessing
 * `s.chainOfThought` throws "The current scope does not have a 'chainOfThought'
 * property." Standard rendering and legacy ChainOfThought are mutually exclusive;
 * this component keeps the renderer on the single supported GroupedParts mode.
 */
export function ThinkingAccordion({
  children,
  count,
}: ThinkingAccordionProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="my-1.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-surface-foreground transition-colors hover:bg-interactive-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-interactive-focus-ring"
      >
        {open ? (
          <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        )}
        <span className="flex-1 text-left font-medium text-sm">
          Thinking
          {count !== undefined && count > 0 && (
            <span className="ml-1.5 text-xs font-normal text-muted-foreground">
              ({count})
            </span>
          )}
        </span>
      </button>
      {open && (
        <div className="rounded-b-lg border-x border-b border-interactive bg-surface-elevated px-3 py-2">
          {children}
        </div>
      )}
    </div>
  );
}
