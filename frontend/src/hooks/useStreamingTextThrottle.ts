import { useEffect, useRef, useState } from "react";

interface UseStreamingTextThrottleInput {
  text: string;
  isStreaming: boolean;
  throttleMs?: number;
  identityKey?: string;
  allowTextReplacement?: boolean;
}

const DEFAULT_STREAMING_TEXT_THROTTLE_MS = 100;

/**
 * While streaming, keep the text from shrinking and batch rapid updates to
 * ~`throttleMs` intervals so the UI does not re-render on every chunk. When
 * streaming ends the latest text is flushed immediately.
 *
 * Ported from the same technique OpenChamber uses for live tool output.
 */
export function useStreamingTextThrottle({
  text,
  isStreaming,
  throttleMs = DEFAULT_STREAMING_TEXT_THROTTLE_MS,
  identityKey,
  allowTextReplacement = false,
}: UseStreamingTextThrottleInput): string {
  const [throttledText, setThrottledText] = useState(text);
  const latestTextRef = useRef(text);
  const throttledTextRef = useRef(throttledText);
  const stateRef = useRef<{
    timer: ReturnType<typeof setTimeout> | null;
    pendingText: string;
    lastEmitAt: number;
  }>({ timer: null, pendingText: text, lastEmitAt: 0 });

  useEffect(() => {
    latestTextRef.current = text;
  }, [text]);

  useEffect(() => {
    throttledTextRef.current = throttledText;
  }, [throttledText]);

  // A new identity (e.g. a different tool call) resets the throttle state.
  useEffect(() => {
    const state = stateRef.current;
    if (state.timer) clearTimeout(state.timer);
    state.timer = null;
    state.pendingText = latestTextRef.current;
    state.lastEmitAt = 0;
    setThrottledText(latestTextRef.current);
  }, [identityKey]);

  useEffect(() => {
    const state = stateRef.current;
    state.pendingText = text;
    const current = throttledTextRef.current;
    // Never shrink while streaming unless replacement is explicitly allowed.
    const stable = isStreaming && !allowTextReplacement && current.length > text.length ? current : text;

    if (!isStreaming) {
      if (state.timer) clearTimeout(state.timer);
      state.timer = null;
      state.lastEmitAt = Date.now();
      setThrottledText(stable);
      return;
    }

    const now = Date.now();
    const remaining = Math.max(0, throttleMs - (now - state.lastEmitAt));
    if (remaining <= 0) {
      if (state.timer) clearTimeout(state.timer);
      state.timer = null;
      state.lastEmitAt = now;
      setThrottledText(stable);
      return;
    }

    if (state.timer) clearTimeout(state.timer);
    state.timer = setTimeout(() => {
      state.timer = null;
      state.lastEmitAt = Date.now();
      setThrottledText((prev) => {
        const pending = state.pendingText;
        return isStreaming && !allowTextReplacement && prev.length > pending.length ? prev : pending;
      });
    }, remaining);

    return () => {
      if (state.timer) clearTimeout(state.timer);
      state.timer = null;
    };
  }, [allowTextReplacement, isStreaming, text, throttleMs]);

  useEffect(
    () => () => {
      if (stateRef.current.timer) clearTimeout(stateRef.current.timer);
    },
    [],
  );

  return throttledText;
}