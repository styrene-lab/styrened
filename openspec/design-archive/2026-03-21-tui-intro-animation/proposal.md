# TUI Intro Animation / Splash Screen

## Intent

Replace the silent 0–8s daemon connection hang at TUI startup with a glitch-convergence intro animation featuring the Styrene double-hexagon logo mark in ASCII/Unicode art. The animation plays while _check_daemon() runs concurrently, then dismisses when the daemon responds (or transitions to DaemonSetupScreen on failure). Uses Tomorrow font branding reference in the wordmark, glitch noise that converges character-by-character to the clean logo over ~30 frames at 50ms = ~1.5s. Status line updates underneath: "starting daemon…" → "connecting…" → "loading…".

See [design doc](../../../docs/tui-intro-animation.md).
