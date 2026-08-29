import { useMemo, useState } from "react";
import type { EnrichedPartState } from "@assistant-ui/react";

type ReasoningPart = Extract<EnrichedPartState, { type: "reasoning" }>;

const SUMMARY_MAX = 90;

/** Flatten markdown to plain text so the collapsed preview reads cleanly. */
function stripMarkdown(text: string): string {
  return text
    .replace(/```[\w]*\n?([\s\S]*?)```/g, (_, inner: string) => inner.trim())
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*{1,3}([^*]+)\*{1,3}/g, "$1")
    .replace(/_{1,3}([^_]+)_{1,3}/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^>\s?/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

function summaryOf(text: string): string {
  if (!text) return "";
  if (text.length <= SUMMARY_MAX) return text;
  const cut = text.lastIndexOf(" ", SUMMARY_MAX);
  return `${text.slice(0, cut > 0 ? cut : SUMMARY_MAX).trimEnd()}...`;
}

/**
 * Collapsible thinking block.
 *
 * While the part is still streaming it stays open so the reasoning is visible
 * as it arrives. Once finished it collapses to a one-line summary, which keeps
 * long chain-of-thought from burying the reply underneath it.
 */
export function ReasoningBlock({ part }: { part: ReasoningPart }) {
  const streaming = part.status?.type === "running";
  const [userExpanded, setUserExpanded] = useState(false);
  const open = streaming || userExpanded;

  const summary = useMemo(
    () => summaryOf(stripMarkdown(part.text)),
    [part.text],
  );

  if (!part.text.trim()) return null;

  return (
    <details
      className="reasoning-block"
      open={open}
      onToggle={(e) => setUserExpanded(e.currentTarget.open)}
    >
      <summary>
        <span className="reasoning-label">{streaming ? "Thinking" : "Thought"}</span>
        {!open && summary ? <span className="reasoning-summary">{summary}</span> : null}
      </summary>
      <div className="reasoning-content">{part.text}</div>
    </details>
  );
}