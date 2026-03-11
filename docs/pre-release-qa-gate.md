---
id: pre-release-qa-gate
title: Pre-Release Visual QA Gate
status: implemented
related: [tui-specification]
tags: [release, qa, tui, process, operator-validation]
open_questions: []
---

# Pre-Release Visual QA Gate

## Overview

Formalize operator-driven visual/interactive QA as a hard gate before any release is cut. The pattern: launch the pre-release TUI, walk through affected screens, sign off, then cut the tag. This gate catches regressions that automated tests miss — layout breakage, theme inconsistencies, interaction flow surprises, and IPC-connected behavior that unit tests mock away. Applies to all releases that touch TUI code. The gate lives in the justfile release recipe and is documented in a QA checklist.

## Research

### What automated tests miss

Textual unit tests (pytest-asyncio + Pilot) test widget existence, reactive state, and message passing — but they cannot catch:
- Layout reflow issues (panel overlaps, truncation, proportional fr units breaking at real terminal widths)
- Theme cascade breakage (color variable changes that look fine in isolation but break contrast in context)
- IPC-connected behavior (tests mock the bridge; real daemon responses may differ in timing or shape)
- First-run UX (wizard flow, daemon not running states)
- Imperial CRT theme rendering on real terminal emulators vs Textual's test harness
- Scroll/focus state after navigation sequences
- Keybinding shadowing by screen stack (unit tests operate on single screens)

### Launch mechanism

TUI entry point: `.venv/bin/styrene` (pyproject.toml scripts.styrene → styrened.tui.__main__:main). Starts the full StyreneApp with embedded daemon (standalone mode by default). Config reads from ~/.styrene/ or ~/.config/styrene/. The pre-release launch uses the local dev install (editable, `pip install -e ".[tui,dev]"`) so it exercises the exact code being released, not a published wheel. No special flags needed — just `styrene` from the venv.

### Current release recipe

justfile `release` recipe: `just release X.Y.Z` → validate → bump version → commit → tag → push → publish (build wheel+sdist, twine upload to PyPI). No QA step exists between validate and bump. The gate should be inserted as a human confirmation step after tests pass and before the version bump is committed — at that point, the code is at release quality and the operator is reviewing the exact artifact that will ship.

## Decisions

### Decision: Gate is inline in `just release` with `--skip-qa` escape hatch

**Status:** decided
**Rationale:** After unit tests pass, `just release` launches `.venv/bin/styrene`, displays the static QA checklist, and blocks on operator confirmation before bumping the version. Confirmation is a simple y/n prompt — pressing n aborts cleanly with no version bump or tag. `just release --skip-qa` bypasses for hotfixes. This makes the gate impossible to skip accidentally on the normal path while preserving flexibility.

### Decision: Static core checklist with git-diff addendum for touched areas

**Status:** decided
**Rationale:** Core checklist is always shown: Home, Nodes/peer workspace (MeshDeviceDetailScreen tabs), Comms, Settings/Network. An addendum is generated from `git diff v$(cat VERSION)..HEAD -- src/styrened/tui/` — if files in a given screen/widget directory changed, those items are flagged as "also review". Static base ensures nothing is ever missed; diff addendum focuses operator attention on what changed this cycle.

### Decision: Gate auto-detects TUI changes; skipped silently for pure daemon releases

**Status:** decided
**Rationale:** `just release` checks `git diff v$(cat VERSION)..HEAD -- src/styrened/tui/` before launching the QA gate. If no TUI files changed, the gate is skipped with a one-line note ("No TUI changes detected — skipping visual QA"). This keeps the release path fast for daemon-only patches while enforcing the gate when it matters.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `scripts/qa_gate.sh` (new) — Gate script: detects TUI changes via git diff, shows checklist + diff addendum, prompts operator sign-off
- `docs/TUI-QA-CHECKLIST.md` (new) — Static QA checklist: core items (Home/Nodes/Comms/Mail/Settings/Nav) + extended checks per changed area
- `justfile` (modified) — release recipe wired to qa_gate.sh; --skip-qa flag for hotfixes; all pytest calls fixed to use .venv/bin/python

### Constraints

- --skip-qa bypass must be explicit positional flag, not default
- Gate silently skips when no TUI changes detected since last tag
- Checklist prompt blocks; n/N aborts cleanly before any version mutation
