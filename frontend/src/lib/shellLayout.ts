/**
 * Shared application-shell layout constants.
 *
 * The authoritative contract for every value here lives in
 * `docs/FRONTEND_UI_SPEC.md` (Section 1 - Application shell). This module only
 * exists so the same formula is defined once instead of being repeated in
 * several components, where the copies could drift apart.
 */

/**
 * Shared content column.
 *
 * Applied to exactly three wrappers so their left and right edges line up:
 *   1. the empty state (inside `ThreadPrimitive.Viewport`)
 *   2. the message-list wrapper (inside `ThreadPrimitive.Viewport`)
 *   3. the INNER wrapper of `ThreadPrimitive.ViewportFooter`
 *
 * The OUTER `ViewportFooter` deliberately keeps its own full-width classes so
 * its background still spans the whole viewport while it is sticky.
 *
 * Breakdown:
 *   - `w-[min(100%,48rem)]` caps the column at 48rem but never overflows.
 *   - `mx-auto` centres it.
 *   - `px-[clamp(0.75rem,2.5vw,1rem)]` is the gutter below 1024px.
 *   - `lg:px-[clamp(1rem,2.5vw,1.5rem)]` is the gutter from 1024px up
 *     (`lg` is the Tailwind default 64rem breakpoint).
 */
export const SHARED_CONTENT_COLUMN =
  "w-[min(100%,48rem)] mx-auto px-[clamp(0.75rem,2.5vw,1rem)] lg:px-[clamp(1rem,2.5vw,1.5rem)]";
