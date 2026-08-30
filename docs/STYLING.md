# RTAI Frontend Styling Convention

## Permanent Rules

1. **Tailwind v4 utilities style React components.** All component layout and presentation uses Tailwind utility classes in `className` props.
2. **Semantic tokens are defined centrally** in `frontend/src/styles/themes.css` and exposed via `@theme inline`.
3. **Components use semantic utilities, not raw palette colors.** Use `bg-background`, `text-foreground`, `border-interactive`, etc. Never `bg-[var(--background)]` when a semantic utility exists.
4. **No new global component CSS classes.** Component styling lives in TSX `className` strings, not in `.css` files.
5. **No `@apply`.** Do not create CSS class aliases for Tailwind utilities.
6. **No CSS Modules or new styling frameworks.** Stick to Tailwind v4 + scoped CSS exceptions only.
7. **Arbitrary values limited to genuine one-off structural calculations.** e.g., `pb-[calc(0.75rem+env(safe-area-inset-bottom))]` is acceptable; repeating them for common patterns is not.
8. **Generated Markdown, Shiki output and unavoidable third-party overrides are the only normal CSS exceptions.** These live in `markdown.css` and `assistant-ui.css`.
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
  assistant-ui.css — Proven third-party overrides that cannot be expressed on React elements.
```

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
