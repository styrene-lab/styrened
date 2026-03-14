---
id: splash-art-variant-selection
title: Splash Art Variant Selection
status: exploring
parent: tui-intro-animation
tags: [tui, splash, ux]
open_questions: []
---

# Splash Art Variant Selection

## Overview

GlitchLogoWidget has LARGE (90×36) and MEDIUM (56×23) art variants. Need a reliable heuristic to auto-select at startup. terminal col×row count is insufficient — a wide 1080p terminal and a 4K terminal can have identical dimensions in characters. The right signal is either (a) explicit user preference, or (b) a proxy for physical cell size / display density.

## Decisions

### Decision: Use col ≥ 160 as the large-variant threshold

**Status:** decided
**Rationale:** CSI 16t pixel cell query is more accurate but async, emulator-dependent (no Terminal.app), and adds startup complexity. col ≥ 160 is a reliable zero-config proxy: 4K terminals are almost always ≥180 cols; 1080p terminals rarely exceed 150 cols at usable font sizes. No env var, no user configuration, just works. Medium is the default/fallback.

## Open Questions

*No open questions.*
