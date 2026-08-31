# RTAI Frontend Styling Convention

## Permanent Rules

1. **Tailwind v4 utilities style React components.** All component layout and presentation uses Tailwind utility classes in `className` props.
2. **Semantic tokens are defined centrally** in `frontend/src/styles/themes.css` and exposed via `@theme inline`.
3. **Components use semantic utilities, not raw palette colors.** Use `bg-background`, `text-foreground`, `border-interactive`, etc. Never `bg-[var(--background)]` when a semantic utility exists.
4. **No new global component CSS classes.** Component styling lives in TSX `className` strings, not in `.css` files.
5. **No `@apply`.** Do not create CSS class aliases for Tailwind utilities.
6. **No CSS Modules or new styling frameworks.** Stick to Tailwind v4 + scoped CSS exceptions only.
7. **Arbitrary values limited to genuine one-off structural calculations.** e.g., `pb-[calc(0.75rem+env(safe-area-inset-bottom))]` is acceptable; repeating them for common patterns is not.
8. **Generated Markdown, Shiki output and unavoidable third-party overrides are the only normal CSS exceptions.** These live in `markdown.css`.
9. **New themes change token values — not individual components.** Edit `themes.css` to swap color palettes.
10. **Styling changes must not alter runtime behavior.** No JavaScript logic changes in styling commits.
11. **Coding and testing are separate agent responsibilities.** This document governs styling code only.

## Accepted Patterns

```tsx
// Semantic utility usage
<div className="bg-background text-foreground border border-interactive">
  <span className="text-muted-foreground text-sm">Label</span>
</div>

// Conditional state with semantic tokens
<div className={`${isActive ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"}`}>

// Responsive variants
<div className="hidden sm:flex gap-2">

// Pseudo-classes
<button className="hover:bg-interactive-hover focus:border-ring transition-colors">
```

## Rejected Patterns

```tsx
// Raw var() in className
<div className="bg-[var(--background)] text-[var(--foreground)]">  // ❌

// New global class definitions in TSX
<div className="my-custom-component">  // ❌ (unless defined in CSS exception file)

// @apply in CSS
.btn { @apply bg-primary text-primary-foreground rounded; }  // ❌

// Hardcoded colors
<div className="bg-blue-500 text-slate-900">  // ❌ (use semantic tokens)

// CSS Modules
import styles from "./Component.module.css"  // ❌
```

## File Structure

```
frontend/src/styles/
  index.css        — Main entry. Imports tailwindcss + all foundation files.
  themes.css       — CSS variable definitions + @theme inline mappings.
  base.css         — html/body/#root resets, focus-visible, scrollbars, keyframes.
  markdown.css     — .message__content descendant selectors for generated Markdown.
```

## Application Shell Contract

The application shell is a **fluid, height-constrained layout** that must never overflow the
viewport and must adapt from a fluid sidebar column (desktop) to an off-canvas drawer (mobile).

> **Canonical source.** Exact shell behaviour, measurements, breakpoint ownership and the
> acceptance checklist are defined in `docs/FRONTEND_UI_SPEC.md` (Section 1). This section
> records only the styling conventions behind them. If the two disagree, the spec wins — do
> not restate or reinterpret its rules here.

### Height / shrink chain (desktop ⇒ mobile continuity)

Every ancestor in the chain must participate so flex children can actually shrink and the
single scrolling region (the thread Viewport) gets the remaining space:

```
#root (height:100%; overflow:hidden)        [base.css]
  └─ App shell <div>      flex h-dvh min-h-0 w-full min-w-0 overflow-hidden
       ├─ <Sidebar/>      w-[clamp(14rem,18vw,18rem)]  (fluid; no resize handle this milestone)
       └─ <main>          flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden
            └─ ChatScreen <div>   flex min-h-0 min-w-0 flex-1 flex-col
                 └─ ThreadPrimitive.Root  flex min-h-0 min-w-0 w-full flex-1 flex-col
                      └─ ThreadPrimitive.Viewport  flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto
```

- `h-dvh` anchors the shell to the viewport. `min-h-0` / `min-w-0` unlock flex shrinking.
- Only **one** region scrolls: `ThreadPrimitive.Viewport` (`overflow-y-auto`). No other ancestor
  in the chain may set `overflow` other than `overflow-hidden`.

### Locked ThreadPrimitive classes (use EXACTLY these)

- `ThreadPrimitive.Root`: `flex min-h-0 min-w-0 w-full flex-1 flex-col`
- `ThreadPrimitive.Viewport`: `flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto`
- `ThreadPrimitive.ViewportFooter`: `sticky bottom-0 z-10 w-full min-w-0 bg-background`

There must be **exactly one** of each. The Composer lives inside `ViewportFooter`.

### Shared content column (48rem cap)

The empty state, the message-list wrapper and the **inner** wrapper of `ViewportFooter` all
use one shared column so their left and right edges line up. The exact formula lives in the
spec (Section 1) and is exported as a single constant — import it rather than retyping the
utilities, so the three call sites cannot drift apart:

```tsx
import { SHARED_CONTENT_COLUMN } from "../lib/shellLayout";

// message list / footer inner wrapper
<div className={`${SHARED_CONTENT_COLUMN} min-w-0`}>
```

Do **not** rely on `ThreadPrimitive.Messages` forwarding `className`.

The **outer** `ViewportFooter` keeps its own locked full-width classes so its background spans
the viewport while sticky. The Composer card itself owns **no** page gutter and adds no second
48rem cap of its own. Never wrap shell content in `max-w-3xl` / `max-w-4xl` / `max-w-5xl` or
`w-[calc(100%-2rem)]`.

Empty state (inside the Viewport, when the thread is empty):

```tsx
<div className={`${SHARED_CONTENT_COLUMN} flex min-h-0 flex-1 flex-col items-center justify-center text-center`}>
```

### Responsive sidebar / drawer

- Breakpoint: the Tailwind default `md` (768px). Above `md` the sidebar is a static column;
  below `md` it becomes an off-canvas drawer. `lg` (1024px) is only the content-column gutter
  breakpoint — it is never a sidebar or drawer breakpoint.
- Desktop width: `w-[clamp(14rem,18vw,18rem)]`. Fluid. There is no resize handle in this
  milestone; user resizing is tracked as *Application Shell 1B* in the tracker.
- Mobile drawer: `max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-40
  max-md:w-[min(85vw,20rem)] max-md:transition-[transform,visibility] max-md:duration-200
  motion-reduce:transition-none max-md:shadow-xl`, plus `max-md:translate-x-0 max-md:visible`
  when open and `max-md:-translate-x-full max-md:invisible` when closed. `visibility` is part
  of the transition list so the closed drawer leaves the tab order without losing the slide
  animation.
- A backdrop `fixed inset-0 z-30 bg-foreground/50 md:hidden` is rendered only while the drawer is
  open; clicking it (or pressing Escape) closes the drawer and restores focus to the menu button.

### Accessibility

- The header menu button is `md:hidden` and carries `aria-expanded` (drawer state),
  `aria-controls="app-sidebar"`, and `ref` to the menu button element.
- The `<aside>` has `id="app-sidebar"`.
- On close, focus returns to the menu button (no new dependencies).
- Interactive buttons keep their desktop `h-8 w-8` sizing and add `max-md:h-11 max-md:w-11`,
  meeting the 44x44px minimum touch target below `md`.

## Semantic Token Categories

| Category | Tokens |
|---|---|
| **Background / Foreground** | `--background`, `--foreground` |
| **Surfaces** | `--card`, `--popover`, `--sidebar`, `--surface-background`, `--surface-elevated`, `--surface-muted` |
| **Interactive** | `--primary`, `--border`, `--ring`, `--interactive`, `--interactive-hover`, `--interactive-active` |
| **Muted** | `--muted`, `--muted-foreground` |
| **Status** | `--status-success`, `--status-warning`, `--status-error`, `--status-info` |
| **Chat** | `--chat-user-message-bg` |
| **Tools** | `--tools-background`, `--tools-border`, `--tools-icon`, `--tools-title` |
| **Markdown** | `--markdown-link`, `--markdown-inline-code`, `--markdown-inline-code-bg` |
| **Syntax** | `--syntax-*` |
| **Typography** | `--text-markdown`, `--text-code`, `--text-meta`, `--text-micro` |
| **Fonts** | `--font-sans`, `--font-mono` |
