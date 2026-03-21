# TUI Intro Animation / Splash Screen — Design Spec (extracted)

> Auto-extracted from docs/tui-intro-animation.md at decide-time.

## Decisions

### Glitch convergence — character-by-character noise resolving to clean logo (decided)

Most cinematic option. Each character position has a randomized unlock frame drawn from a distribution weighted toward center-outward. Before unlock: shows CRT noise char (▓▒░█▄▀▌▐◆■). After unlock: shows final logo char. 30 frames @ 50ms = ~1.5s total. Concurrent with daemon polling so zero added latency. Fits Imperial CRT theme.

### Terminal font: document Tomorrow, render with JetBrains Mono Unicode compat (decided)

Textual cannot set terminal fonts — the emulator controls this. Tomorrow is already the declared font-sans in styrene_brand.py. ASCII art must look great in any monospace font (JetBrains Mono, Fira Code, SF Mono). We add a docs/TERMINAL-SETUP.md recommending Tomorrow or JetBrains Mono. The wordmark in the splash uses Unicode block chars that match Tomorrow's geometric, condensed, extrabold aesthetic regardless of terminal font.
