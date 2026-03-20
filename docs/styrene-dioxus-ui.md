---
id: styrene-dioxus-ui
title: Styrene Dioxus UI — Web Dashboard + Mobile App
status: exploring
tags: [dioxus, rust, mobile, web, dashboard, cross-platform, ui]
open_questions:
  - Does the Dioxus app talk to the daemon over a local Unix socket (same as Python TUI IPC) or does it embed styrene-rs library crates directly (in-process)?
  - Where does the Dioxus app crate live — inside styrene-rs workspace, a new styrene-app repo, or the existing styrene-web-bridge repo (renamed)?
issue_type: epic
priority: 2
---

# Styrene Dioxus UI — Web Dashboard + Mobile App

## Overview

Dioxus as the single UI framework for all non-TUI Styrene surfaces: web dashboard (replaces Axum+HTMX plan), iOS/Android mobile app, and potentially a desktop GUI companion. Shares the same Rust daemon service layer via IPC/broadcast channels. Consolidates web+mobile into one dependency tree rather than maintaining Axum + a separate mobile framework. The Ratatui TUI (styrened-rs) remains the operator/SSH surface — Dioxus does not replace it.

## Research

### Dioxus Platform Status (March 2026)

- **Web (WASM)**: production-ready in 0.6. SSR + hydration supported. Good choice for web dashboard.
- **Desktop** (WebView/WRY): "mostly ready" per community consensus. macOS/Linux/Windows. Good for operator companion app.
- **Mobile (iOS/Android)**: `dx serve --platform ios/android` ships in 0.6. Hot reload, asset bundling, fast rebuilds. Still maturing but viable for an MVP.
- **TUI (dioxus-tui / Rink)**: **removed from the official Dioxus repo**. Was briefly in the Blitz experiment, then dropped. Last crate version 0.4.3. A community fork restored it but it is unmaintained upstream. **Not a viable TUI path** — Ratatui remains the correct choice for SSH/operator surfaces.
- dioxus-tui was removed because the rendering model mismatch (DOM/CSS vs terminal cells) was fundamental, not fixable.
- Dioxus 0.6 release blog: https://dioxuslabs.com/blog/release-060/

### Dependency consolidation rationale

- **Before**: styrene-web-bridge planned as Axum + HTMX/Leptos (Python IPC consumer). Mobile would require a separate framework (Swift/Kotlin native, or React Native, or a second Rust framework).
- **After**: Dioxus handles web dashboard (WASM + SSR) and mobile (iOS/Android) from a single codebase. Drops: Axum (as primary web UI layer), HTMX, and any mobile-specific framework.
- Axum may still be retained as the thin HTTP server backing Dioxus SSR/fullstack — but as an implementation detail of Dioxus fullstack, not a separately maintained surface with its own routing and templates.
- The Python `styrene-web-bridge` repo in the workspace is in planning phase — no implementation to migrate.
- IPC contract: Dioxus app connects to styrened-rs daemon via the same broadcast/mpsc channel architecture or a local Unix socket — same as Ratatui TUI. The daemon doesn't know or care what's rendering.
- Shared Rust business logic (models, service traits, wire protocol parsing) lives in styrene-rs crates, imported by both the daemon binary and the Dioxus app crate.

## Decisions

### Decision: Use Dioxus for web dashboard and mobile — not Axum+HTMX

**Status:** decided
**Rationale:** Mobile is a stated requirement and requires a cross-platform Rust UI framework. Dioxus covers mobile (iOS/Android) in 0.6. Since we need Dioxus for mobile, using it for the web dashboard as well consolidates the dependency tree — one framework, one component model, shared Rust business logic. The alternative (Axum+HTMX for web, separate mobile framework) means maintaining two UI paradigms with no shared code. Dioxus is heavier than a minimal Axum setup but the mobile requirement makes the weight acceptable. Ratatui remains the operator/SSH TUI surface — Dioxus does not replace it.

### Decision: Ratatui (styrened-rs) remains the TUI — Dioxus does not target terminal

**Status:** decided
**Rationale:** dioxus-tui was removed from the Dioxus project; the rendering model mismatch between DOM/CSS and terminal cells is fundamental. The SSH/operator interface on edge devices requires a real TUI. Ratatui is the correct tool; the Omegon codebase provides a directly reusable pattern. These are complementary surfaces, not competing choices.

## Open Questions

- Does the Dioxus app talk to the daemon over a local Unix socket (same as Python TUI IPC) or does it embed styrene-rs library crates directly (in-process)?
- Where does the Dioxus app crate live — inside styrene-rs workspace, a new styrene-app repo, or the existing styrene-web-bridge repo (renamed)?
