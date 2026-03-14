---
id: splash-cascade-glitch
title: Splash Cascade + Glitch Animation
status: exploring
parent: tui-intro-animation
tags: [tui, animation, splash]
open_questions: []
---

# Splash Cascade + Glitch Animation

## Overview

Compound animation: rows cascade downward Matrix-style (top→bottom reveal), and as each character first appears it immediately enters its per-character glitch-to-clean sequence. Double effect: positional cascade phase + noise convergence phase per character.

## Decisions

### Decision: Two-phase per-character timing: (appear_frame, unlock_frame)

**Status:** decided
**Rationale:** Each non-blank character gets a tuple (appear, unlock). Before appear: render as space (invisible). Between appear and unlock: noise/glitch. After unlock: clean final glyph. _assign_unlock_frames returns list[list[tuple[int,int]]] instead of list[list[int]]. Cascade phase fills first ~55% of TOTAL_FRAMES (rows appear linearly top-to-bottom with ±2 frame jitter). Glitch window is random 3–N frames after appear, N scaling with distance from horizontal centre (centre chars glitch longer). Bright _ACCENT flash on frame==appear, dims toward _DIM as unlock approaches.

### Decision: Replace static tagline with animated StartupChecklist widget

**Status:** decided
**Rationale:** 4 items mapped to real daemon startup phases: reticulum transport → mesh discovery → lxmf routing → hub connection. States: hidden/pending(·)/active(▸)/done(✓)/failed(✗). _poll_daemon drives state transitions. Items appear one-by-one as phases progress — feels tied to real events. Single #status label retained below checklist for freeform messages. #tagline label removed.

## Open Questions

*No open questions.*
