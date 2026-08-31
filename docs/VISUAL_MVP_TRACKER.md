# RTAI Visual MVP Tracker

This is the permanent progress tracker for the RTAI frontend visual implementation.
Every frontend agent must read this tracker before starting work and update it when
phase status changes.

## Status definitions

| Status | Meaning |
|---|---|
| **Planned** | Feature is on the roadmap but no work has begun |
| **Specified** | Design specification exists in docs/FRONTEND_UI_SPEC.md |
| **Implemented in source** | Code exists in frontend/src/ and matches the spec |
| **CI build verified** | npm run build passes in GitHub Actions |
| **Visually verified** | Screenshot/artifact inspection confirms correct rendering |
| **Blocked** | Waiting on external dependency (backend API, design decision, etc.) |
| **Deferred** | Intentionally postponed to a later milestone |

## Current baseline

- Branch: feature/react-ui-foundation
- Starting SHA: bdf21d0
- Build contract commit: HEAD - this commit replaces the broad spec with an
  incremental build contract covering only the active shell + composer sections
- Current CI state: Green for documentation-only commits
- Known Playwright status: No E2E tests exist yet; Playwright repair deferred
- Recovery stash: stash@{0}: recovery: attachment and shell changes before branch repair - untouched

## Build phases

| # | Phase | Scope | Status | Source SHA | CI run | Visual evidence | Remaining work |
|---|---|---|---|---|---|---|---|
| 1 | Build contract | Incremental spec covering active shell + composer only; future sections as placeholders | Specified | HEAD | N/A (doc only) | N/A | None |
| 2 | Application shell | h-dvh shell, flex shrink chain, header h-12 (48px), sidebar desktop+mobile drawer, scroll ownership, 48rem column formula | Planned | — | — | — | Correct header height; verify gutter formula; finalize drawer inert contract |
| 3 | Composer and capability controls | Input auto-grow; send/stop toggle; footer left-group (capability selectors only); runtime-driven state; no hardcoded labels | Planned | — | — | — | Restructure footer layout; verify send/stop cycle; test disconnected state |
| 4 | Messages | User bubbles; assistant cards; ToolCard; avatars; scroll-to-bottom button | Deferred | — | — | — | Requires OpenChamber message rendering study per spec section 3 |
| 5 | Sidebar and session history | Session list; new session; folder selector polish | Deferred | — | — | — | Requires OpenChamber sidebar behavior study per spec section 4 |
| 6 | Header/top bar polish | Session title editing; navigation controls | Deferred | — | — | — | Requires OpenChamber header study per spec section 5 |
| 7 | Right rail / context panel | 44px rail; 380-1400px panel; drag-reorderable icons | Deferred | — | — | — | Requires backend surface registry (spec section 6) |
| 8 | Message actions | Timestamps; context menu; export; toasts | Deferred | — | — | — | Per spec section 7 |
| 9 | Responsive polish | Verify no layout break at 320/375/768/1024/1280/1440/1920/2560px | Planned | — | — | — | Test all breakpoints |
| 10 | Accessibility polish | Focus order, ARIA labels, reduced motion, inert drawer, 44px touch targets | Planned | — | — | — | Audit per spec sections 1-2 |
| 11 | Replacement tests | Update component tests for new shell/composer structure | Planned | — | — | — | Tests in tests/frontend/ must match new structure |
| 12 | Visual verification | Screenshots at every breakpoint/state from acceptance checklist | Planned | — | — | — | Capture before each milestone merge |

## Handoff log
| Date | SHA | Agent/task | Area | Result | CI | Visual status | Next action |
|---|---|---|---|---|---|---|---|
| 2026-08-31 | 88d47c3 | Agnes (spec writer) | Design specification | Created initial docs/FRONTEND_UI_SPEC.md and docs/VISUAL_MVP_TRACKER.md | N/A | N/A | — |
| 2026-08-31 | ca17f8e | Agnes (spec finalizer) | Locked contract + decision resolution | Added section 0 locked contract; resolved 5 open decisions; clarified right panel dimensions | N/A | N/A | Spec rewrite phase |
| 2026-08-31 | d3ff517 | Agnes (spec rewriter) | Full specification rewrite | Rewrote spec to 467 lines; corrected header height (48px), composer width (48rem cap), mobile breakpoint (1024px); fixed accessibility contract | N/A | N/A | Restore deferred features to roadmap |
| 2026-08-31 | bdf21d0 | Agnes (roadmap restorer) | Deferred feature restoration | Restored 6 future interaction milestones to tracker; added right-rail boundary note; clarified current inline feedback behavior; split out-of-scope into deferred vs permanently excluded | N/A | N/A | Begin shell milestone implementation |
| 2026-08-31 | bdf21d0 | Agnes (contract writer) | Incremental build contract | Replaced broad 482-line spec with focused build contract; active sections = shell + composer; future sections as placeholders; no features deleted | N/A | N/A | Begin shell milestone implementation |

## Permanent agent rule

Every frontend agent must:

1. Read docs/FRONTEND_UI_SPEC.md (the build contract), docs/STYLING.md, and this tracker before touching any frontend source.
2. Follow the locked specification for active sections — do not redesign during implementation.
3. Update this tracker in the same commit when any phase status changes.
4. Never mark a phase Visually verified without screenshot evidence or artifact inspection.
5. If a spec conflict is discovered, pause and report to the maintainers before proceeding.
