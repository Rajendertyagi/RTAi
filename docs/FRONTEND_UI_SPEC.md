# RTAI Frontend UI Specification

Design authority: OpenChamber source. RTAI inherits its measured layout, spacing,
and responsive behavior. Deviations are listed explicitly in the permitted
differences section below.

## 1. Purpose and design authority

This document defines the visual and layout contract for the RTAI web frontend.
It is grounded in measured OpenChamber behavior; RTAI retains its own backend,
Protocol v1, assistant-ui primitives, and runtime capability system.

OpenChamber source files studied for this specification:

| File | Measurement taken from |
|---|---|
| `packages/ui/src/components/layout/MainLayout.tsx:102` | `h-[100dvh]` shell, flex layout chain |
| `packages/ui/src/components/layout/Sidebar.tsx:7-9` | Default 280px, range 280-500px, pointer-resize |
| `packages/ui/src/components/layout/Header.tsx:1565` | `h-12` (48px) desktop; macOS override to `h-12` or `h-14` |
| `packages/ui/src/styles/typography.css:83-125` | `.chat-column`, `.chat-input-column`, `.chat-message-column` formulas |
| `packages/ui/src/components/chat/ChatContainer.tsx:1462-1515` | Composer slot, scroll-to-bottom button, StatusRow positioning |
| `packages/ui/src/components/chat/composer/ui/ComposerFooter.tsx:192-256` | Footer left-group / right-group layout |
| `packages/ui/src/components/chat/ChatEmptyState.tsx:15` | Centered flex column, min-h-full |
| `packages/ui/src/components/layout/ContextPanelRail.tsx:294` | `w-11` (44px) fixed rail |
| `packages/ui/src/components/layout/ContextPanel.tsx:52-54` | Min 380, default 600, max 1400 |
| `packages/ui/src/styles/design-system.css:9` | `--oc-header-height: 56px` CSS var (runtime-measured, not hardcoded) |
| `packages/ui/src/styles/mobile.css:4` | `@media (max-width: 1024px)` responsive breakpoint |

## 2. Permitted RTAI differences

These are the only deviations from the OpenChamber reference. No other changes
are permitted without amending this document first.

| # | RTAI difference | Reason |
|---|---|---|
| 1 | RTAI branding, labels, and session titles | Product identity |
| 2 | `assistant-ui` Thread/Viewport/ViewportFooter/Composer primitives | Framework choice; OpenChamber uses its own message list |
| 3 | Agent, model, mode, and thinking controls populated dynamically from backend capability events | Protocol v1 capability discovery; OpenChamber uses config store |
| 4 | ACP attachment availability negotiated at runtime per active adapter/session | Provider-neutral; never hardcoded by provider name |
| 5 | Tailwind CSS v4 semantic utilities and RTAI theme tokens in `frontend/src/styles/themes.css` | Styling convention per `docs/STYLING.md` |

## 3. OpenChamber measurement table

All measurements below are verified from source. Values that differ from the
previous RTAI spec are noted.

| Element | Measured value | Source | Notes |
|---|---|---|---|
| Application shell | `h-[100dvh]` flex, overflow hidden | `MainLayout.tsx:102` | Matches existing STYLING.md `h-dvh` contract |
| Header height | `h-12` = 48px (desktop default) | `Header.tsx:1565` | **Corrected**: previous spec said 56px; macOS variant may use `h-12` or `h-14` |
| Left sidebar default | 280px (`SIDEBAR_CONTENT_WIDTH`) | `Sidebar.tsx:7` | Resizable 280-500px via pointer events |
| Left sidebar min/max | 280px / 500px | `Sidebar.tsx:8-9` | RTAI uses fixed `w-[clamp(14rem,18vw,18rem)]` (224-288px) -- narrower range, no resize handle |
| Mobile breakpoint | `@media (max-width: 1024px)` | `mobile.css:4` | **Corrected**: previous spec used 768px (`md`); OpenChamber uses 1024px for mobile adaptations |
| Message column width | `min(100%, 48rem)` + `margin-inline: auto` | `typography.css:84,225` | Capped at 768px prose width |
| Input/composer column width | `min(100%, 48rem)` + `margin-inline: auto` | `typography.css:93-97` | **Corrected**: previous spec said composer is `w-full` uncapped; measured source shows same 48rem cap |
| Column gutters (below 1024px) | `clamp(0.75rem, 2.5vw, 1rem)` | `typography.css:86` | Tapers from 0.75rem to 1rem |
| Column gutters (1024px+) | `clamp(1rem, 2.5vw, 1.5rem)` | `typography.css:114-124` | Tapers from 1rem to 1.5rem |
| Right rail width | `w-11` = 44px fixed | `ContextPanelRail.tsx:294` | |
| Context panel min | 380px (`CONTEXT_PANEL_MIN_WIDTH`) | `ContextPanel.tsx:52` | |
| Context panel default | 600px (`CONTEXT_PANEL_DEFAULT_WIDTH`) | `ContextPanel.tsx:54` | |
| Context panel max | 1400px (`CONTEXT_PANEL_MAX_WIDTH`) | `ContextPanel.tsx:53` | |
| Footer layout | Left: attachments/utility actions; Right: model controls + send/stop | `ComposerFooter.tsx:194-256` | |

## 4. Application-shell anatomy

```
#root (height:100%; overflow:hidden; background:var(--background))     [base.css]
  └─ App shell <div>  flex h-dvh min-h-0 w-full min-w-0 overflow-hidden
       ├─ <Sidebar/>      w-[clamp(14rem,18vw,18rem)] bg-sidebar border-r border-border shrink-0
       │   (max-md:hidden on desktop; off-canvas drawer on mobile, see section 7)
       └─ <main>          flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden
            └─ ChatScreen  flex min-h-0 min-w-0 flex-1 flex-col
                 ├─ <header>   h-12 shrink-0 flex items-center border-b border-interactive bg-surface-background px-4
                 └─ ThreadPrimitive.Root  flex min-h-0 min-w-0 w-full flex-1 flex-col
                      └─ ThreadPrimitive.Viewport  flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto
                           ├─ Empty state (thread.isEmpty) -- centered, full Viewport height
                           ├─ Messages wrapper
                           │    .chat-column: max-w-[48rem] mx-auto px-[clamp(0.75rem,2.5vw,1rem)]
                           │    (gutters increase to clamp(1rem,2.5vw,1.5rem) at >= 1024px)
                           │    <ThreadPrimitive.Messages>
                           └─ ThreadPrimitive.ViewportFooter  sticky bottom-0 z-10 w-full min-w-0 bg-background
                                ├─ <StatusBar />  h-8 flex items-center gap-2 border-t
                                └─ .chat-input-column: max-w-[48rem] mx-auto px-[...]
                                     <Composer />
```

**Scroll ownership**: exactly one region scrolls -- `ThreadPrimitive.Viewport`
(`overflow-y-auto`). No other ancestor in the chain sets overflow other than
`overflow-hidden`. `ViewportFooter` is a sibling of the messages wrapper inside
`Viewport`, not a child of the message-width wrapper.

## 5. Dimensions and responsive matrix

### Breakpoints

| Token | Value | Used for |
|---|---|---|
| `md` | 768px | Menu button visibility (`md:hidden`), sidebar static/drawer toggle |
| `lg` | 1024px | Mobile adaptations, gutter increase, drawer close threshold |

The responsive breakpoint for layout changes is **1024px**, matching OpenChamber.
The Tailwind `md` (768px) breakpoint is retained only for the menu button
visibility pattern already present in the codebase.

### Dimension table

| Element | < 768px (phone) | 768-1023px (tablet) | 1024-1440px (laptop) | 1441-1920px (desktop) | > 1920px (wide) |
|---|---|---|---|---|---|
| Header height | 48px | 48px | 48px | 48px | 48px |
| Left sidebar | Drawer: min(85vw, 20rem) | Static: clamp(14rem,18vw,18rem) | Static: clamp(14rem,18vw,18rem) | Static: clamp(14rem,18vw,18rem) capped at 18rem | Static: 18rem (288px) |
| Message column | max-w-[48rem] mx-auto, gutters clamp(0.75rem,2.5vw,1rem) | Same | Same | Same; gutters clamp(1rem,2.5vw,1.5rem) | Same; gutters 1.5rem |
| Composer column | max-w-[48rem] mx-auto, same gutters as message | Same | Same | Same; gutters clamp(1rem,2.5vw,1.5rem) | Same; gutters 1.5rem |
| Right rail | Hidden | Hidden | 44px fixed (deferred) | 44px fixed (deferred) | 44px fixed (deferred) |
| Context panel | N/A | N/A | 380-1400px (deferred) | 380-1400px (deferred) | 380-1400px (deferred) |

### Content-rail formula

Both the message column and the composer column share the same constrained-width
pattern from OpenChamber:

```
column-width  = min(100%, 48rem)
margin-inline = auto
padding-inline = clamp(0.75rem, 2.5vw, 1rem)         (below 1024px)
padding-inline = clamp(1rem,   2.5vw, 1.5rem)        (at 1024px and above)
```

At 320px: content = 288px (gutter 1rem per side).
At 768px: content = ~576px (gutter ~1.5rem per side).
At 1024px: content = 768px (48rem cap active, gutters clamp(1rem,2.5vw,1.5rem)).
At 1920px: content = 768px (48rem cap, gutters 1.5rem per side).

Code blocks and tool cards exceed the 48rem measure and scroll horizontally
within their container; this never creates page-level horizontal overflow.

## 6. Typography and semantic color roles

### Typography

All type tokens are defined in `frontend/src/styles/themes.css` and exposed via
`@theme inline`. Measured OpenChamber values match RTAI's current definitions.

| Role | Size | Weight | Line height | Token / class |
|---|---|---|---|---|
| Markdown body / assistant text | 0.9375rem (15px) | 400 | 1.6 | `--text-markdown` |
| User message text | 0.9375rem (15px) | 400 | 1.6 | Same as assistant |
| Composer input | 0.875rem (14px) | 400 | 1.5 | `text-sm` |
| Sidebar section labels | 0.75rem (12px) | 500 | 1.2 | Uppercase tracking-widest |
| Header session title | 0.9375rem (15px) | 400 | 1.4 | `text-[14px] font-normal leading-tight` |
| Capability selectors | 0.75rem (12px) | 400 | 1.3 | `text-xs` |
| Metadata / status text | 0.75rem (12px) | 400 | 1.3 | `text-xs text-muted-foreground` |
| Empty-state heading | 1.5rem (24px) | 400 | 1.3 | `text-2xl font-normal` |
| Empty-state subtext | 0.875rem (14px) | 400 | 1.5 | `text-sm text-muted-foreground` |
| Code / inline code | 0.8125rem (13px) | 400 | 1.5 | `--text-code` |
| Micro text | 0.8125rem (13px) | 400 | 1.4 | `--text-micro` |
| Tool card title | 0.875rem (14px) | 500 | 1.4 | `text-sm font-medium` |

### Color roles

All colors use semantic tokens from `frontend/src/styles/themes.css`. Components
use Tailwind utility classes (`bg-background`, `text-foreground`, `border-interactive`,
etc.) -- never raw `var(--...)` in className strings.

| Role | Light | Dark | Utility |
|---|---|---|---|
| App background | `--background: oklch(0.97 0.02 85)` | `--background: oklch(0.16 0.01 30)` | `bg-background` |
| Primary text | `--foreground: oklch(0.25 0.02 40)` | `--foreground: oklch(0.85 0.02 90)` | `text-foreground` |
| Sidebar bg | `--sidebar: oklch(0.94 0.015 80)` | `--sidebar: oklch(0.18 0.01 40)` | `bg-sidebar` |
| Elevated surface | `--surface-elevated: var(--card)` | `--surface-elevated: oklch(0.19 0.01 40)` | `bg-surface-elevated` |
| Muted surface | `--surface-muted: oklch(0.9 0.015 75)` | `--surface-muted: oklch(0.33 0.01 40)` | `bg-surface-muted` |
| Border | `--border: oklch(0.85 0.02 70)` | `--border: oklch(0.31 0.01 35)` | `border-border` |
| Interactive border | `--interactive-border: var(--border)` | same | `border-interactive` |
| Interactive hover | `color-mix(in srgb, var(--primary) 10%, transparent)` | `--interactive-hover` | `hover:bg-interactive-hover` |
| Primary accent | `--primary: oklch(0.65 0.2 55)` (orange) | `--primary: oklch(0.77 0.17 85)` (gold) | `bg-primary` |
| Muted text | `--muted-foreground: oklch(0.45 0.02 50)` | `--muted-foreground: oklch(0.75 0.02 80)` | `text-muted-foreground` |
| Focus ring | `--ring: oklch(0.65 0.2 55)` | `--ring: oklch(0.77 0.17 85)` | `focus:ring-ring` |
| Success | `--status-success: oklch(0.58 0.15 145)` | same | `bg-status-success` |
| Warning | `--status-warning: oklch(0.75 0.18 85)` | same | `bg-status-warning` |
| Error | `--status-error: oklch(0.58 0.22 25)` | same | `bg-status-error` |
| Info | `--status-info: oklch(0.62 0.18 230)` | same | `bg-status-info` |
| Chat user message bg | `color-mix(in srgb, var(--primary) 12%, transparent)` | `color-mix(in srgb, var(--primary) 20%, transparent)` | `bg-chat-user-message-bg` |
| Tools background | `color-mix(in srgb, var(--surface-muted) 30%, transparent)` | `--tools-background` | `bg-tools-background` |
| Tools border | `color-mix(in srgb, var(--interactive-border) 60%, transparent)` | `--tools-border` | `border-tools-border` |

## 7. Left sidebar and header

### Left sidebar

- **Desktop width**: `w-[clamp(14rem,18vw,18rem)]` (224px minimum, scales
  proportionally, 288px maximum). Fixed width -- no resize handle (simpler than
  OpenChamber's resizable 280-500px panel; RTAI will wire a resizable sidebar
  only if Phase 5 product requirements demand it).
- **Background**: `bg-sidebar text-sidebar-foreground`.
- **Border**: `border-r border-border`.
- **Shrink**: `shrink-0` -- sidebar never compresses when the main area narrows.
- **Overflow**: `overflow-hidden` -- sidebar content scrolls independently.

### Header

- **Height**: `h-12` (48px), `shrink-0`.
- **Background**: `bg-surface-background`.
- **Border**: `border-b border-interactive`.
- **Padding**: `px-4`.
- **Layout**: `flex items-center justify-between`.

Left side: menu button (mobile only, `md:hidden`, 32x32px touch target), RTAI
title (`text-lg font-medium`), connection dot (8x8px, green/red).
Right side: agent info label (`ml-auto text-sm text-muted-foreground`).

### Mobile sidebar (drawer, < 1024px)

- Off-canvas: `max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-40
  max-md:w-[min(85vw,20rem)] max-md:transition-transform max-md:duration-200
  max-md:shadow-xl`
- Open: `max-md:translate-x-0`; Closed: `max-md:-translate-x-full`
- Backdrop: `fixed inset-0 z-30 bg-foreground/50 md:hidden` rendered only while open
- On close: focus returns to the menu button; drawer is removed from tab order

## 8. Thread, messages, empty state, and scroll ownership

### Scroll ownership

Exactly one scrolling region exists: `ThreadPrimitive.Viewport` (`overflow-y-auto`).
No other ancestor in the flex chain sets overflow other than `overflow-hidden`.
The `ViewportFooter` is a **sibling** of the messages wrapper inside `Viewport`,
not a child of the message-width column.

### Empty state

Rendered when `thread.isEmpty` (via `AuiIf`):

```
flex min-h-0 flex-1 flex-col items-center justify-center
chat-column  (max-w-[48rem] mx-auto, gutter-clamped padding)
text-center
```

- Heading: `text-2xl font-normal text-foreground`
- Subtext: `mt-2 text-sm text-muted-foreground`
- Vertically centered in remaining Viewport space

### Messages

- Inter-message vertical gap: `py-2` (8px)
- User message: right-aligned (`flex-row-reverse`), max-w-[75%] bubble,
  `bg-chat-user-message-bg border border-primary/20 rounded-xl p-2.5`
- Assistant message: left-aligned, `bg-card border border-border rounded-xl p-2.5 w-full`
- Avatars: 28x28px circles -- user `bg-surface-muted text-surface-muted-foreground` label "U",
  assistant `bg-primary text-primary-foreground` label "AI"
- Code blocks: `overflow-x-auto`, `white-space: pre`, monospace font
- Tool cards: collapsible, icon + title + preview row; expanded output scrolls horizontally

### Scroll-to-bottom control

When the user has scrolled up more than 200px from the bottom, a scroll-to-bottom
button appears positioned above the composer, aligned within the `chat-input-column`
(so its left edge matches the composer's left edge). The button is a glass pill
(`rounded-full`, backdrop-blur) with an arrow-down icon. During streaming it
shows the current working-status label. This matches OpenChamber
`ScrollToBottomButton.tsx`.

## 9. Composer anatomy and runtime controls

### Position and width

Inside `ThreadPrimitive.ViewportFooter` (sticky bottom, full width). The composer
sits inside the `.chat-input-column` wrapper -- same `max-w-[48rem] mx-auto` constraint
and same gutter as the message column. This ensures visual alignment between
messages and the composer.

```
ViewportFooter (sticky bottom-0 z-10 w-full)
  └─ .chat-input-column (max-w-[48rem] mx-auto, gutter-clamped padding)
       ├─ StatusBar  (h-8, border-t)
       └─ Composer   (w-full within column, rounded-xl border bg-surface-elevated)
```

### Composer card

- Background: `bg-surface-elevated`
- Border: `border border-interactive`
- Radius: `rounded-xl` (12px)
- Focus ring: `focus-within:ring-2 focus-within:ring-interactive-focus-ring`
- Internal padding: `p-3` on root flex container

### Input

- Minimum: 1 row (~36px). Maximum: 200px via inline style clamp.
- Auto-grow: `onInput` sets `style.height = "auto"` then `style.height = min(scrollHeight, 200}px")`.
- Overflow: `overflow-y-auto` when exceeding max.
- Placeholder: "Ask anything..."

### Footer row layout (matching OpenChamber)

| Side | Controls |
|---|---|
| **Left** | Attachment button (when available), command/slash button, capability selectors (agent, model, mode, thinking) |
| **Right** | Send button (disabled when empty) or Stop button (when running) |

`CapabilitySelectors` (the actual component name in `frontend/src/components/CapabilitySelectors.tsx`)
renders runtime-driven agent/model/mode/thinking controls. Each control follows the
tri-state contract: dropdown when multiple options exist, chip when exactly one,
disabled-with-reason when unavailable. No control is hardcoded to any provider.

### Send / Stop

- Send: 36x36px rounded-lg, `bg-primary text-primary-foreground`, ArrowUp icon.
  Disabled when input is empty: `disabled:cursor-not-allowed disabled:opacity-40`.
- Stop: replaces Send when `activeTurnId !== null`. 36x36px, `bg-status-error`.
  Hover: `hover:opacity-85`.

### Disabled / pending states

| State | Visual |
|---|---|
| No selection available | `disabled:cursor-not-allowed disabled:opacity-50` |
| Selection in flight | 12px spinning border-circle next to control label |
| Selection failed | `lastError` surfaced in StatusBar as truncated red text |
| Disconnected | Send visible but prompts are rejected with an honest reason shown (never silently dropped) |

## 10. Right rail / context-panel shell contract

### Right rail

- Width: `w-11` (44px) fixed, `flex h-full flex-shrink-0 flex-col items-center gap-1 bg-background py-2`
- Contains icon buttons (36x36px, `h-9 w-9`). Active icon: `text-primary`; inactive:
  `text-muted-foreground hover:text-foreground`.
- Configuration button at bottom for surface order (deferred).

### Context panel

- Min width: 380px (`CONTEXT_PANEL_MIN_WIDTH`)
- Default width: 600px (`CONTEXT_PANEL_DEFAULT_WIDTH`)
- Max width: 1400px (`CONTEXT_PANEL_MAX_WIDTH`)
- Resize: pointer-events on 3px left-edge handle; `transition-[width] duration-200 ease-[cubic-bezier(0.22,1,0.36,1)]`
- Tab label truncation: 24 characters
- **Closed by default**; opened only by clicking a rail icon
- On narrow main area (< 640px): panel overlays chat as `absolute inset-0 z-20 bg-background`
- Rail hidden on mobile (< 768px)

All right-rail and context-panel implementation is **deferred** -- no backend
surface registry exists yet. This section defines the target shape.

## 11. Interaction and accessibility states

### Focus order

1. Menu button (mobile only)
2. Sidebar contents (when open on mobile)
3. Backdrop (click to close; not a tab stop)
4. Header elements (non-interactive)
5. Composer input (primary interaction point)
6. Send / Stop button
7. Capability selector controls (tabbable selects)
8. StatusBar (non-interactive, skipped)

### Drawer accessibility

- Closed drawer: must not remain tabbable. Use `inert` attribute or unmount the
  drawer content when closed -- transform alone is insufficient.
- Open drawer: modal semantics (`role="dialog"` or equivalent), `aria-modal`,
  focus contained within, Escape key closes and restores focus to menu button,
  backdrop click closes.
- Backdrop: `pointer-events-auto` for click, not a keyboard tab stop.

### Touch targets

- All interactive buttons: minimum 44x44px hit area on mobile (< 1024px).
- Desktop buttons: 32x32px minimum (`w-8 h-8`).
- Composer Send/Stop: 36x36px (`h-9 w-9`).

### Focus indicators

- Global: `outline: 2px solid var(--ring); outline-offset: 2px` on `:focus-visible`.
- Non-focus-visible elements: `outline: none`.
- Composer root: `focus-within:ring-2 focus-within:ring-interactive-focus-ring`.

### Reduced motion

- `@media (prefers-reduced-motion: reduce)`: drawer transitions are instant
  (`transition-none`), busy-pulse reduces to static opacity, sidebar resize
  animation is suppressed.

### Disconnected / error states

- Connection dot: `bg-status-error` (red) when disconnected.
- StatusBar text: "Disconnected" when not ready.
- Send button: disabled with visible reason text; prompts are **never silently dropped**.
- Selection failures: shown in StatusBar as truncated red text, not swallowed.

## 12. Acceptance criteria

### Shell

- [ ] App fills entire viewport with no page-level scrollbar.
- [ ] Only `ThreadPrimitive.Viewport` scrolls; header, sidebar, and composer are fixed.
- [ ] Flex shrink chain is correct: `min-h-0` / `min-w-0` on every ancestor.

### Sidebar

- [ ] Desktop: visible static column at `clamp(14rem,18vw,18rem)` width.
- [ ] Mobile (< 768px): hidden behind off-canvas drawer; menu button opens it.
- [ ] Drawer uses `inert` or equivalent when closed (not tabbable).
- [ ] Escape closes drawer and restores focus to menu button.
- [ ] Backdrop is not a keyboard tab stop.

### Thread / messages

- [ ] Empty state is vertically centered with heading + subtext.
- [ ] Messages align left (assistant) or right (user) with correct avatars.
- [ ] Message column is capped at 48rem with centered gutters.
- [ ] Code blocks scroll horizontally within their container; no page overflow.

### Composer

- [ ] Composer column shares the same 48rem cap and gutters as the message column.
- [ ] Input auto-grows from 1 row to 200px max.
- [ ] Send is disabled when input is empty; Stop appears during active turn.
- [ ] Capability selectors show runtime values; unavailable controls show reasons.
- [ ] Footer layout: controls on the left, Send/Stop on the right.

### Responsive

- [ ] No layout break at 320px, 375px, 768px, 1024px, 1280px, 1440px, 1920px, 2560px.
- [ ] Touch targets are at least 44x44px on mobile (< 1024px).
- [ ] Message and composer columns stay aligned at every breakpoint.

### Accessibility

- [ ] Focus-visible ring is 2px solid ring color with 2px offset.
- [ ] All interactive elements have `aria-label` or visible text.
- [ ] `prefers-reduced-motion`: animations are suppressed.
- [ ] Screen reader announces connection state on change.

## 13. Explicit implementation boundaries

### In scope (Shell milestone)

- `App.tsx` -- shell root
- `Sidebar.tsx` -- left navigation (desktop + mobile drawer)
- `ChatPanel.tsx` -- flex main wrapper
- `ChatScreen.tsx` -- header + ThreadPrimitive hierarchy
- `Composer.tsx` -- input + send/stop
- `CapabilitySelectors.tsx` -- runtime-driven selectors
- `Message.tsx` -- per-message rendering
- `ToolCard.tsx` -- collapsible tool call card
- `StatusBar.tsx` -- connection + agent + error display

### Deferred (separate milestones)

- Right rail and context panel (no backend surface registry)
- Session history list in sidebar (Phase 5 SQLite dependency)
- Native session resume (backend dependency)
- Attachment support in composer (adapter-dependent; server adapter not yet exposed)
- Scroll-to-bottom button (measured OpenChamber behavior; implement if simple)

### Out of scope (never in this spec)

- Focus mode (hide sidebar, expand composer)
- Full-screen mobile composer with drag handle
- Conversation timeline / turn navigation rail
- Work status panel (context usage, subagent cost)
- Skeleton-loading systems
- Toast-notification system
- Drag-reordering right-rail icons
- Provider-specific hardcoded controls
- Message export menus, hover timestamps, or context menus
