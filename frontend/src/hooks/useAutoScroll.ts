import { useEffect, useRef, type RefObject } from "react";

// Keeps the message list pinned to the bottom as content grows.
export function useAutoScroll<T extends HTMLElement>(deps: unknown): RefObject<T> {
  const ref = useRef<T>(null);

  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deps]);

  return ref;
}
