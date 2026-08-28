import { useSyncExternalStore } from "react";
import { getTheme, subscribeTheme } from "../lib/theme";
import type { ColorScheme } from "../lib/shikiHighlighter";

/**
 * Current scheme for Shiki, read from the shared theme store.
 *
 * useSyncExternalStore keeps React in step with the document without a second
 * independent copy of the state, so the app chrome and the code-block theme
 * cannot disagree.
 */
export function useColorScheme(): ColorScheme {
  return useSyncExternalStore(subscribeTheme, getTheme, getTheme);
}
