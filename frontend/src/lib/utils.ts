// Copied from official Assistant UI registry — immutable commit
// b6e7ab88b5e6e60866695d31a08adc3a80f449ff (pinned @assistant-ui/react@0.15.17 /
// @assistant-ui/core@0.3.16).
// Source: packages/ui/src/lib/utils.ts
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
