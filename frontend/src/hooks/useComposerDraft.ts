import { useEffect, useRef, useState } from "react";

const DRAFT_KEY = "rtai-composer-draft";
const DEBOUNCE_MS = 250;

function readDraft(): string {
  try {
    return localStorage.getItem(DRAFT_KEY) ?? "";
  } catch {
    // Private mode / storage disabled: drafts are a nicety, not a requirement.
    return "";
  }
}

/**
 * Composer text that survives a reload.
 *
 * Writes are debounced so typing does not hit localStorage on every keystroke.
 * An empty draft removes the key rather than storing "".
 */
export function useComposerDraft() {
  const [text, setText] = useState(readDraft);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (timer.current !== undefined) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      try {
        if (text) localStorage.setItem(DRAFT_KEY, text);
        else localStorage.removeItem(DRAFT_KEY);
      } catch {
        /* ignore */
      }
    }, DEBOUNCE_MS);
    return () => {
      if (timer.current !== undefined) window.clearTimeout(timer.current);
    };
  }, [text]);

  const clearDraft = () => setText("");

  return { text, setText, clearDraft };
}
