---
id: tui-intro-animation
title: "TUI Intro Animation / Splash Screen"
status: decided
parent: tui-specification
tags: [tui, ux, animation, branding]
open_questions: []
branches: ["feature/tui-intro-animation"]
openspec_change: tui-intro-animation
---

# TUI Intro Animation / Splash Screen

## Overview

Replace the silent 0–8s daemon connection hang at TUI startup with a glitch-convergence intro animation featuring the Styrene double-hexagon logo mark in ASCII/Unicode art. The animation plays while _check_daemon() runs concurrently, then dismisses when the daemon responds (or transitions to DaemonSetupScreen on failure). Uses Tomorrow font branding reference in the wordmark, glitch noise that converges character-by-character to the clean logo over ~30 frames at 50ms = ~1.5s. Status line updates underneath: "starting daemon…" → "connecting…" → "loading…".

## Decisions

### Decision: Glitch convergence — character-by-character noise resolving to clean logo

**Status:** decided
**Rationale:** Most cinematic option. Each character position has a randomized unlock frame drawn from a distribution weighted toward center-outward. Before unlock: shows CRT noise char (▓▒░█▄▀▌▐◆■). After unlock: shows final logo char. 30 frames @ 50ms = ~1.5s total. Concurrent with daemon polling so zero added latency. Fits Imperial CRT theme.

### Decision: Terminal font: document Tomorrow, render with JetBrains Mono Unicode compat

**Status:** decided
**Rationale:** Textual cannot set terminal fonts — the emulator controls this. Tomorrow is already the declared font-sans in styrene_brand.py. ASCII art must look great in any monospace font (JetBrains Mono, Fira Code, SF Mono). We add a docs/TERMINAL-SETUP.md recommending Tomorrow or JetBrains Mono. The wordmark in the splash uses Unicode block chars that match Tomorrow's geometric, condensed, extrabold aesthetic regardless of terminal font.

## Open Questions

*No open questions.*
