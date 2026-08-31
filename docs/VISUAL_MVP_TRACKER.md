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
- **Current CI state**: See latest GitHub Actions run for `feature/react-ui-foundation`
- **Known Playwright status**: No E2E tests exist yet (Phase 8)
- **Recovery stash**: `stash@{0}: recovery: attachment and shell changes before branch repair` -- untouched

## Phase table

| # | Phase | Scope | Status | Source SHA | CI run | Visual evidence | Remaining work |
|---|---|---|---|---|---|---|---|
| 1 | Design specification | Create `docs/FRONTEND_UI_SPEC.md` and `docs/VISUAL_MVP_TRACKER.md` | Specified | `88d47c3` (this commit) | N/A | N/A (doc only) | None |
| 2 | Fluid application shell | Shell fills viewport; no overflow; flex shrink chain correct | Implemented in source | `88d47c3` | TBD | TBD | Verify no page scroll on any viewport |
| 3 | Left sidebar | Desktop static column + mobile off-canvas drawer with backdrop | Implemented in source | `88d47c3` | TBD | TBD | Phase 5: wire to SQLite session list |
| 4 | Thread / empty state | Empty centered state; message alignment; avatar styling | Implemented in source | `88d47c3` | TBD | TBD | Add scroll-to-bottom button (deferred) |
| 5 | Composer | Input auto-grow; send/stop toggle; capability controls | Implemented in source | `88d47c3` | TBD | TBD | Attachments (deferred); expanded mode (deferred) |
| 6 | Message presentation | User bubbles; assistant cards; ToolCard; StatusBar | Implemented in source | `88d47c3` | TBD | TBD | Message timestamps, copy, hover actions (deferred) |
| 7 | Right sidebar / rail | Target defined in spec; no implementation yet | Deferred | — | — | — | Requires context surface registry backend |
| 8 | Responsive polish | Verify all breakpoints; no layout break at any width | In progress | `88d47c3` | TBD | TBD | Test at 320, 375, 768, 1024, 1280, 1440, 1920, 2560px |
| 9 | Accessibility | Focus order, ARIA labels, reduced motion, contrast | Partially implemented | `88d47c3` | TBD | TBD | Focus trap in drawer (Phase 8); screen reader testing |
| 10 | Visual verification | Screenshots at every breakpoint/state from acceptance checklist | Planned | — | — | — | Capture before each milestone merge |
| 11 | Replacement tests | Update existing component tests for new shell/components | Planned | — | — | — | Tests in `tests/frontend/` must match new structure |

## Handoff log

| Date | SHA | Agent/task | Area | Result | CI | Visual status | Next action |
|---|---|---|---|---|---|---|---|
| 2026-08-31 | `88d47c3` | Agnes (spec writer) | Design specification | Created `docs/FRONTEND_UI_SPEC.md` (806 lines) and `docs/VISUAL_MVP_TRACKER.md` | N/A | N/A | Begin shell milestone implementation |

## Permanent agent rule

Every frontend agent must:

1. Read `docs/FRONTEND_UI_SPEC.md`, `docs/STYLING.md`, and this tracker before touching any frontend source.
2. Follow the locked specification -- do not redesign during implementation.
3. Update this tracker in the same commit when any phase status changes.
4. Never mark a phase "Visually verified" without screenshot evidence or artifact inspection.
5. If a spec conflict is discovered, pause and report to the maintainers before proceeding.
