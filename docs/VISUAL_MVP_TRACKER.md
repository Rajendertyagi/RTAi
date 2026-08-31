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
- **Documentation commit (unpushed)**: `025e015` — `docs(ui): define OpenChamber-inspired frontend specification`
- **Current CI state**: Green for `88d47c3`; documentation commit not yet pushed
- **Known Playwright status**: No E2E tests exist yet (Phase 8); Playwright repair deferred to separate task
- **Recovery stash**: `stash@{0}: recovery: attachment and shell changes before branch repair` -- untouched

## Phase table

| # | Phase | Scope | Status | Source SHA | CI run | Visual evidence | Remaining work |
|---|---|---|---|---|---|---|---|
| 1 | Design specification | Create `docs/FRONTEND_UI_SPEC.md` and `docs/VISUAL_MVP_TRACKER.md`; resolve all open decisions | Specified | `88d47c3` | N/A (doc only) | N/A | None |
| 2 | Fluid application shell | Shell fills viewport; no overflow; flex shrink chain correct; locked contract enforced | Implemented in source | `88d47c3` | N/A | N/A | Visual verification at 320/768/1024/1920px |
| 3 | Left sidebar | Desktop static column + mobile off-canvas drawer with backdrop | Implemented in source | `88d47c3` | N/A | N/A | Phase 5: wire to SQLite session list |
| 4 | Thread / empty state | Empty centered state; message alignment; avatar styling; scroll-to-bottom button | Implemented in source (button deferred) | `88d47c3` | N/A | N/A | Add scroll-to-bottom glass pill; message timestamps; copy action |
| 5 | Composer | Input auto-grow; send/stop toggle; capability controls | Implemented in source | `88d47c3` | N/A | N/A | Attachments (adapter unavailable); mobile expanded mode (deferred) |
| 6 | Message presentation | User bubbles; assistant cards; ToolCard; StatusBar | Implemented in source | `88d47c3` | N/A | N/A | Hover actions, timestamps |
| 7 | Right sidebar / rail | Target defined in spec; no implementation yet | Deferred | — | — | — | Requires context surface registry backend |
| 8 | Responsive polish | Verify all breakpoints; no layout break at any width | Planned | — | — | — | Screenshot capture at 320/375/768/1024/1280/1440/1920/2560px |
| 9 | Accessibility | Focus order, ARIA labels, reduced motion, contrast | Partially implemented | `88d47c3` | N/A | N/A | Focus trap in drawer; screen reader testing |
| 10 | Visual verification | Screenshots at every breakpoint/state from acceptance checklist | Planned | — | — | — | Capture before each milestone merge |
| 11 | Replacement tests | Update existing component tests for new shell/components | Planned | — | — | — | Tests in `tests/frontend/` must match new structure |

## Handoff log

| Date | SHA | Agent/task | Area | Result | CI | Visual status | Next action |
|---|---|---|---|---|---|---|---|
| 2026-08-31 | `88d47c3` | Agnes (spec writer) | Design specification | Created `docs/FRONTEND_UI_SPEC.md` (1063 lines) and `docs/VISUAL_MVP_TRACKER.md` | N/A | N/A | Begin shell milestone implementation |
| 2026-08-31 | `88d47c3` | Agnes (spec writer) | Rail layout decision | Updated spec to dual-column: `max-w-[48rem]` message column + `w-full` composer (OpenChamber pattern) | N/A | N/A | Ready for implementation |
| 2026-08-31 | `025e015` | Agnes (spec finalizer) | Locked contract + decision resolution | Added section 0 locked contract; resolved all 5 open decisions; clarified right panel dimensions from OpenChamber source | N/A | N/A | Amend and push finalized spec; begin shell implementation |

## Permanent agent rule

Every frontend agent must:

1. Read `docs/FRONTEND_UI_SPEC.md`, `docs/STYLING.md`, and this tracker before touching any frontend source.
2. Follow the locked specification -- do not redesign during implementation.
3. Update this tracker in the same commit when any phase status changes.
4. Never mark a phase "Visually verified" without screenshot evidence or artifact inspection.
5. If a spec conflict is discovered, pause and report to the maintainers before proceeding.
