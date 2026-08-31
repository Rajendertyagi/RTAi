# RTAI Visual MVP Tracker

This is the permanent progress tracker for the RTAI frontend visual implementation.
Every frontend agent must read this tracker before starting work and update it when
phase status changes.

## Status definitions

| Status | Meaning |
|---|---|
| **Planned** | Feature is on the roadmap but no work has begun |
| **Specified** | Design specification exists in `docs/FRONTEND_UI_SPEC.md` |
| **Implemented in source** | Code exists in `frontend/src/` and matches the spec |
| **CI build verified** | `npm run build` passes in GitHub Actions |
| **Visually verified** | Screenshot/artifact inspection confirms correct rendering |
| **Blocked** | Waiting on external dependency (backend API, design decision, etc.) |
| **Deferred** | Intentionally postponed to a later milestone |

## Current baseline

- **Branch**: `feature/react-ui-foundation`
- **Starting SHA**: `88d47c3`
- **Documentation commit**: `ca17f8e` — `docs(ui): define OpenChamber-inspired frontend specification`
- **Specification revision**: This commit — corrected measurements, resolved decisions, removed invented features
- **Current CI state**: Green for `ca17f8e` (documentation only)
- **Known Playwright status**: No E2E tests exist yet; Playwright repair deferred to separate task
- **Recovery stash**: `stash@{0}: recovery: attachment and shell changes before branch repair` — untouched

## Phase table

| # | Phase | Scope | Status | Source SHA | CI run | Visual evidence | Remaining work |
|---|---|---|---|---|---|---|---|
| 1 | Design specification | Rewritten spec aligned to OpenChamber measurements; all open decisions resolved | Specified | `ca17f8e` | N/A (doc only) | N/A | None |
| 2 | Fluid application shell | `h-dvh` shell, flex shrink chain, no page overflow | Planned | — | — | — | Implement shell per spec section 4 |
| 3 | Left sidebar | Desktop static column + mobile off-canvas drawer with `inert` focus exclusion | Planned | — | — | — | Implement drawer per spec section 7 |
| 4 | Thread / empty state | Empty centered state; message alignment; scroll-to-bottom button | Planned | — | — | — | Implement per spec sections 8-9 |
| 5 | Composer | Input auto-grow; send/stop toggle; CapabilitySelectors footer layout | Planned | — | — | — | Implement per spec section 9 |
| 6 | Message presentation | User bubbles; assistant cards; ToolCard; StatusBar | Planned | — | — | — | Implement per spec section 8 |
| 7 | Right sidebar / rail | Target defined in spec; no implementation yet | Deferred | — | — | — | Requires context surface registry backend |
| 8 | Responsive polish | Verify all breakpoints; no layout break at any width | Planned | — | — | — | Test at 320/375/768/1024/1280/1440/1920/2560px |
| 9 | Accessibility | Focus order, ARIA labels, reduced motion, `inert` drawer, 44px touch targets | Planned | — | — | — | Implement per spec section 11 |
| 10 | Visual verification | Screenshots at every breakpoint/state from acceptance checklist | Planned | — | — | — | Capture before each milestone merge |
| 11 | Replacement tests | Update existing component tests for new shell/components | Planned | — | — | — | Tests in `tests/frontend/` must match new structure |

## Handoff log

| Date | SHA | Agent/task | Area | Result | CI | Visual status | Next action |
|---|---|---|---|---|---|---|---|
| 2026-08-31 | `88d47c3` | Agnes (spec writer) | Design specification | Created initial `docs/FRONTEND_UI_SPEC.md` and `docs/VISUAL_MVP_TRACKER.md` | N/A | N/A | — |
| 2026-08-31 | `ca17f8e` | Agnes (spec finalizer) | Locked contract + decision resolution | Added section 0 locked contract; resolved 5 open decisions; clarified right panel dimensions | N/A | N/A | Spec rewrite phase |
| 2026-08-31 | `ca17f8e` | Agnes (spec rewriter) | Full specification rewrite | Rewrote spec to 467 lines; corrected header height (48px), composer width (48rem cap), mobile breakpoint (1024px); removed invented features; fixed accessibility contract | N/A | N/A | Begin shell milestone implementation |

## Permanent agent rule

Every frontend agent must:

1. Read `docs/FRONTEND_UI_SPEC.md`, `docs/STYLING.md`, and this tracker before touching any frontend source.
2. Follow the locked specification -- do not redesign during implementation.
3. Update this tracker in the same commit when any phase status changes.
4. Never mark a phase "Visually verified" without screenshot evidence or artifact inspection.
5. If a spec conflict is discovered, pause and report to the maintainers before proceeding.
