---
id: tui-light-dark-mode
title: "TUI Light/Dark Mode"
status: decided
open_questions: []
---

# TUI Light/Dark Mode

## Overview

Assess feasibility and design of light/dark mode switching in the Styrene TUI given Textual's theme API and the existing ColorCascade system.

## Research

### Textual Theme API (v0.8.1)

Textual has a first-class theme system. App.register_theme(Theme), App.theme = name, App.action_toggle_dark(), App.action_change_theme(). Theme() constructor takes dark: bool. Available palette variables: primary, secondary, accent, foreground, background, surface, panel, success, warning, error, boost, luminosity_spread, text_alpha, plus arbitrary variables dict. action_toggle_dark() is built-in but currently blocked in app.py to prevent accidental theme replacement.

### Existing ColorCascade system

ColorCascade derives all theme colors algorithmically from a single phosphex (phosphor) color. to_textual_theme() produces a Textual Theme with dark=True hardcoded. All backgrounds are near-black tinted toward phosphex. 32 Forge World presets (e.g. styrene=#00b4b4). The cascade has no concept of light mode — bg_screen, bg_panel etc all use create_tinted_dark() which hardcodes very dark base_brightness values (10, 12, 15). Rich markup colors in widgets (e.g. #5f9ea0, #a8d8d8) are also hardcoded hex, not CSS variables — they would not respond to a light theme automatically.

### Tweakcn profile → Textual Theme mapping

STYRENE_DARK in styrene_brand.py is already a tweakcn token dict (sourced from tweakcn.com/themes/cmly8fsie000204l8fqt54s1p). create_styrene_theme() maps it to Textual.Theme manually. Tweakcn token schema: primary/primary_foreground, foreground, background, card/card_foreground, popover/popover_foreground, secondary/secondary_foreground, muted/muted_foreground, accent/accent_foreground, destructive/destructive_foreground, border, input, ring, chart1-5, sidebar_* (12 tokens). Textual Theme fields: primary, secondary, accent, foreground, background, surface, panel, success, warning, error, boost, dark, variables dict. Mapping: tweakcn primary→Textual primary+accent, background→background, card→surface, border→panel, muted_foreground→text-muted variable, destructive→warning+error. Tweakcn exports as CSS HSL vars or hex; existing code uses hex.

### Tweakcn registry API confirmed

Registry endpoint: GET https://tweakcn.com/r/themes/{id} (extract id from https://tweakcn.com/themes/{id}). Returns JSON: {name, cssVars: {theme: {fonts, radius}, light: {...}, dark: {...}}, type: "registry:style"}. Colors are OKLCH format: "oklch(L C H)" with L in [0,1], C >=0, H in degrees. OKLCH→hex implemented in tweakcn.py using pure math (no external deps). Conversion validated: oklch(0.2063 0.0120 277.8347)=#16171d, oklch(0.8556 0.1555 179.7932)=#00f0d3 — matching existing hand-tuned hex values exactly.

### TweakcnProfile implementation

src/styrened/tui/themes/tweakcn.py: TweakcnProfile dataclass with dark/light/meta dicts. from_url(url) fetches registry JSON (handles both tweakcn.com/themes/{id} and /r/themes/{id}). from_registry_json(data) parses dict. to_textual_theme(mode="dark") maps tokens to Textual Theme. theme_name(mode) returns "{name}-{mode}". parse_color() converts OKLCH/hex to hex. STYRENE_THEME_KEY updated to "styrene-dark". styrene_brand.py now embeds the full registry JSON snapshot (_STYRENE_REGISTRY) and delegates create_styrene_theme() to TweakcnProfile.to_textual_theme("dark"). All 3105 unit tests pass.

## Decisions

### Decision: Replace one-off styrene_brand.py with generic TweakcnProfile → Textual.Theme pipeline

**Status:** decided
**Rationale:** New themes should be data not code. TweakcnProfile captures the full tweakcn token schema. tweakcn_to_textual(profile, dark, name) is the single conversion function. STYRENE_DARK becomes the first TweakcnProfile instance. Ships with a few built-in profiles. Import path: paste tweakcn JSON/CSS export → register as theme → switch in UI.

### Decision: Custom tweakcn URL in Settings Appearance panel

**Status:** decided
**Rationale:** Since themes are tweakcn profiles, users can supply their own tweakcn URL. TUI fetches the JSON, parses as TweakcnProfile, registers and applies live. URL persisted to tui.yaml as ui.custom_theme_url and reloaded on startup. Built-ins + custom URL are mutually exclusive selections in the Appearance tab.

## Open Questions

*No open questions.*
