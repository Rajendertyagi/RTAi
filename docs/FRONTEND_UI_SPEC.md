# RTAI Frontend Build Contract

Design authority: OpenChamber source. RTAI inherits its measured layout, spacing,
and responsive behavior. Deviations are listed explicitly in the permitted
differences section below.

## 0. Rules for every frontend agent

- Follow OpenChamber reference behavior unless this document explicitly lists an
  RTAI exception.
- Before editing any section, study the matching OpenChamber files and record
  them in that section's "OpenChamber files studied" table.
- Do not invent sizes, colors, layout, controls, or interactions.
- Do not hardcode backend capability lists. Agent/model/mode/thinking/attachments
  must come from runtime/backend events.
- Use Tailwind v4 semantic utilities only.
- No new global component CSS.
- No `@apply`.
- No CSS Modules / CSS-in-JS / new styling framework.
- Coding and testing stay separate.
- If the contract does not define a UI decision, stop and ask instead of guessing.
- **This document is the canonical source of truth for exact UI behaviour.**
  `docs/STYLING.md` holds reusable styling conventions and points here for exact
  shell rules. `docs/VISUAL_MVP_TRACKER.md` tracks progress and links here
  instead of restating the rules. When the three disagree, this document wins.

## 1. Active section: Application shell

Status: implemented in source — CI build and browser verification pending

OpenChamber files studied:
| File | Measurement taken from |
|---|---|
| `packages/ui/src/components/layout/MainLayout.tsx:102` | `h-[100dvh]` shell, flex layout chain |
| `packages/ui/src/components/layout/Sidebar.tsx:7-9` | Default 280px, range 280-500px, pointer-resize |
| `packages/ui/src/components/layout/Header.tsx:1565` | `h-12` (48px) desktop; macOS override to `h-12` or `h-14` |
| `packages/ui/src/styles/typography.css:83-125` | `.chat-column`, `.chat-input-column`, `.chat-message-column` formulas |
| `packages/ui/src/components/chat/ChatEmptyState.tsx:15` | Centered flex column, min-h-full |
| `packages/ui/src/styles/mobile.css:4` | `@media (max-width: 1024px)` responsive breakpoint |
| `packages/ui/src/styles/design-system.css:9` | `--oc-header-height: 56px` CSS var (runtime-measured, not hardcoded) |

RTAI files affected:
| File | Role |
|---|---|
| `frontend/src/App.tsx` | Shell root: `flex h-dvh min-h-0 w-full min-w-0 overflow-hidden` |
| `frontend/src/components/Sidebar.tsx` | Left navigation (desktop fluid column + mobile off-canvas drawer) |
| `frontend/src/components/ChatPanel.tsx` | Flex main wrapper (`flex-1 min-h-0 min-w-0 flex-col overflow-hidden`) |
| `frontend/src/components/ChatScreen.tsx` | Header + ThreadPrimitive hierarchy + ViewportFooter |
| `frontend/src/lib/shellLayout.ts` | `SHARED_CONTENT_COLUMN` — single source for the column formula |

Locked rules:
- **Shell height**: `h-dvh` (100dvh), `overflow-hidden`, flex column. No page-level
  scrollbar.
- **Header height**: `h-12` (48px), per OpenChamber measurement at `Header.tsx:1565`.
- **Sidebar width (desktop, >= 768px)**: `w-[clamp(14rem,18vw,18rem)]`
  (224px minimum, 288px maximum) — a fluid column that tracks the viewport.
  `shrink-0`, `bg-sidebar`, `border-r border-border`.
  **No resize handle in this milestone.** User resizing is a pending follow-up
  tracked as *Application Shell 1B* in `docs/VISUAL_MVP_TRACKER.md`. It is
  deferred, not rejected, and must not be implemented ad hoc — it needs its own
  specification update here before any code is written.
- **Mobile sidebar (< 768px)**: off-canvas drawer triggered by menu button.
  `max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-40 max-md:w-[min(85vw,20rem)]`.
  Uses `inert` or equivalent when closed (not tabbable) — implemented with
  `max-md:invisible` while closed, which removes the whole subtree from the tab
  order and from the accessibility tree. `visibility` is part of the transition
  (`max-md:transition-[transform,visibility]`) so the slide-out still animates.
  Escape key closes and restores focus to menu button. Backdrop is not a
  keyboard tab stop.
- **Main content**: `flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden`.
- **Scroll ownership**: exactly one scrolling region — `ThreadPrimitive.Viewport`
  (`overflow-y-auto`). No other ancestor sets overflow other than `overflow-hidden`.
  `ViewportFooter` is a sibling of the messages wrapper inside `Viewport`.
- **Breakpoints**: the sidebar drawer and the menu button switch at the Tailwind
  default `md` (768px); the menu button uses `md:hidden`. `lg` (1024px) is used
  **only** for the shared content-column gutter switch below. 1024px is never a
  sidebar or drawer breakpoint.
- **Shared content column** (from `typography.css:83-125`):
  ```
  width: min(100%, 48rem);
  margin-inline: auto;
  padding-inline: clamp(0.75rem, 2.5vw, 1rem)         (< 1024px)
  padding-inline: clamp(1rem,   2.5vw, 1.5rem)        (>= 1024px)
  ```
  Tailwind form (exported as `SHARED_CONTENT_COLUMN` from
  `frontend/src/lib/shellLayout.ts`):
  ```
  w-[min(100%,48rem)] mx-auto px-[clamp(0.75rem,2.5vw,1rem)] lg:px-[clamp(1rem,2.5vw,1.5rem)]
  ```
  Applied to exactly three wrappers so their edges line up:
    1. the empty state,
    2. the message-list wrapper,
    3. the **inner** wrapper of `ViewportFooter` (the one holding StatusBar and
       Composer).
  The **outer** `ViewportFooter` keeps its own full-width locked classes so its
  background still spans the viewport while sticky. The Composer adds no second
  48rem cap of its own.
- **Accessibility**: all interactive buttons ≥ 44x44px touch target on mobile
  (`max-md:h-11 max-md:w-11` layered on the desktop `h-8 w-8`); focus-visible
  ring 2px solid ring color with 2px offset; `prefers-reduced-motion` suppresses
  drawer transitions and busy animations.

RTAI exceptions:
- Sidebar is a fluid `clamp()` column with no resize handle in this milestone.
  OpenChamber's sidebar is user-resizable 280-500px. That behaviour is tracked
  as *Application Shell 1B* and must be specified in this section before it is
  built.
- RTAI uses `assistant-ui` ThreadPrimitive/Viewport/ViewportFooter/Composer
  primitives; OpenChamber uses its own message list and input.
- RTAI theme tokens live in `frontend/src/styles/themes.css` with Tailwind v4
  `@theme inline` — no raw `var(--...)` in className strings.

Acceptance checklist:
- [ ] App fills entire viewport with no page-level scrollbar.
- [ ] Only `ThreadPrimitive.Viewport` scrolls; header, sidebar, and footer are fixed.
- [ ] Flex shrink chain: `min-h-0` / `min-w-0` on every ancestor from shell to viewport.
- [ ] Header height is `h-12` (48px).
- [ ] Desktop sidebar visible at `clamp(14rem,18vw,18rem)` width, never compresses.
- [ ] Mobile (< 768px): sidebar hidden behind off-canvas drawer; menu button opens it.
- [ ] Drawer uses `inert` or equivalent when closed; Escape closes and restores focus.
- [ ] Backdrop is not a keyboard tab stop.
- [ ] Empty state, message column and footer inner wrapper all share the 48rem
  centered column; gutters follow the clamp formula at both breakpoint ranges.
- [ ] Outer `ViewportFooter` stays full width.
- [ ] No layout break at 320px, 375px, 768px, 1024px, 1280px, 1440px, 1920px, 2560px.

## 2. Active section: Composer and capability controls

Status: partly implemented — footer layout needs left-group restructuring

OpenChamber files studied:
| File | Measurement taken from |
|---|---|
| `packages/ui/src/components/chat/ChatContainer.tsx:1462-1515` | Composer slot, scroll-to-bottom button, StatusRow positioning |
| `packages/ui/src/components/chat/composer/ui/ComposerFooter.tsx:192-256` | Footer left-group / right-group layout |
| `packages/ui/src/styles/typography.css:93-97` | `.chat-input-column` width formula (same 48rem cap as message column) |

RTAI files affected:
| File | Role |
|---|---|
| `frontend/src/components/Composer.tsx` | Input + send/stop toggle + footer controls |
| `frontend/src/components/CapabilitySelectors.tsx` | Runtime-driven agent/model/mode/thinking controls |
| `frontend/src/components/StatusBar.tsx` | Connection status + error display |

Locked rules:
- **Position**: inside `ThreadPrimitive.ViewportFooter` (sticky `bottom-0 z-10`).
  Composer sits inside the shared content column wrapper — same 48rem cap and same
  gutters as the message column for visual alignment.
- **Width**: inherits the shared content column from Section 1. The Composer must
  not add a second, independent 48rem cap.
- **Input**: auto-grow from 1 row (~36px) to 200px max via `scrollHeight` clamp.
  `overflow-y-auto` when exceeding max. Placeholder: "Ask anything…".
- **Left controls** (footer left-group): attachment button (when available),
  command/slash button, capability selectors (agent, model, mode, thinking).
  All left-group items render only when runtime/backend exposes them — no stubs.
- **Right controls** (footer right-group): Send button (disabled when empty) or
  Stop button (when `activeTurnId !== null`).
- **Send/Stop**: Send is 36x36px (`h-9 w-9`), `rounded-lg`, `bg-primary
  text-primary-foreground`. Disabled state: `disabled:cursor-not-allowed
  disabled:opacity-40`. Stop replaces Send when running: `bg-status-error`,
  hover `opacity-85`.
- **Capability controls** (`CapabilitySelectors.tsx`): runtime-driven via chat
  store. Tri-state contract per control:
  - Multiple options → enabled dropdown
  - Single option → disabled chip showing label
  - No options + reason → disabled chip with reason text
  - No options + no reason → omitted entirely
  - Pending selection → 12px spinner next to label
  - Selection failure → `lastError` surfaced in StatusBar as truncated red text
  No control is hardcoded to any provider or adapter.
- **Send button disabled states**: disabled when input empty or disconnected with
  visible reason text. Prompts are **never silently dropped**.
- **Accessibility**: Send/Stop have `aria-label`; all capability controls have
  `aria-label`; status bar is skipped in tab order but announces connection
  state on change.

RTAI exceptions:
- OpenChamber `ComposerFooter` has a richer left-group (attachment, focus-mode,
  permission-auto-accept, session-goal buttons). RTAI left-group is simplified
  to only what runtime exposes — no focus-mode button (deferred), no permission
  auto-accept (deferred).
- RTAI uses `assistant-ui` `ComposerPrimitive` instead of OpenChamber's own input;
  auto-grow logic is inline-style based (matching OpenChamber's approach).
- RTAI `StatusBar` is a separate component below the composer within the footer
  column; OpenChamber uses `StatusRowContainer`.

Acceptance checklist:
- [ ] Composer column shares the same 48rem cap and gutters as the message column.
- [ ] Input auto-grows from 1 row to 200px max; overflows vertically when taller.
- [ ] Footer left-group: capability selectors rendered left; attachment/command
  buttons only when runtime exposes them.
- [ ] Footer right-group: Send (disabled when empty) or Stop (when active turn).
- [ ] Capability selectors reflect runtime state; unavailable controls show reasons.
- [ ] Send is disabled with visible reason when disconnected; no silent drops.
- [ ] Selection failures appear in StatusBar as truncated red text.
- [ ] All interactive controls have `aria-label` or visible text.

## 3. Future section: Messages

Status: not designed yet

Do not implement until OpenChamber message rendering is studied and this section
is filled. Planned scope: user bubbles (right-aligned), assistant cards
(left-aligned), ToolCard (collapsible), avatars, code block horizontal scroll,
message alignment, scroll-to-bottom button.

OpenChamber files to study:
- `packages/ui/src/components/chat/ChatContainer.tsx` — message list rendering
- `packages/ui/src/components/chat/message/` — per-message part renderers
- `packages/ui/src/components/chat/components/ScrollToBottomButton.tsx`

## 4. Future section: Sidebar and session history

Status: not designed yet

Do not implement until OpenChamber session sidebar behavior is studied and this
section is filled. Planned scope: session list, new-session action, session
resume (backend dependency), persistent folder selector.

OpenChamber files to study:
- `packages/ui/src/components/layout/Sidebar.tsx` — sidebar structure
- `packages/ui/src/components/session/SessionSidebar.tsx` — session list

## 5. Future section: Header/top bar

Status: not designed yet

Do not implement until OpenChamber header controls are studied and this section
is filled. Current implementation has a minimal header (title, connection dot,
agent label); future work may add session title editing, navigation controls,
and window chrome integration.

OpenChamber files to study:
- `packages/ui/src/components/layout/Header.tsx` — header structure and controls

## 6. Future section: Right rail / context panel

Status: future

Keep as future. Do not delete from roadmap. Do not implement until backend/runtime
surface registry exists. Target shape (measured from OpenChamber):
- Rail: `w-11` (44px) fixed, icon buttons 36x36px, keyboard-accessible.
- Panel: min 380px, default 600px, max 1400px, resize handle, tab labels
  truncated at 24 characters, closed by default.
- Initial rail order is fixed; drag-reordering is a later customization milestone.

OpenChamber files to study:
- `packages/ui/src/components/layout/ContextPanelRail.tsx:294` — rail width
- `packages/ui/src/components/layout/ContextPanel.tsx:52-54` — panel dimensions

## 7. Future section: Message actions, timestamps, export, toasts

Status: future

Keep these as future features. Do not delete. Do not implement now.

| Future capability | Planned milestone | Current status |
|---|---|---|
| Message timestamps | Message polish | Deferred |
| Message context menu (copy, select-all) | Message actions | Deferred |
| Conversation export (markdown transcript) | History and portability | Deferred; requires export contract |
| Toast / notification system | Shared application feedback | Deferred; use inline errors in current milestone |
| Right-rail icon actions | Context-panel shell | Deferred until surface registry exists |
| Drag-reordering right-rail icons | Context-panel customization | Deferred until fixed rail behavior is stable |
