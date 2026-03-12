#!/usr/bin/env bash
# Pre-release visual QA gate.
# Called by `just release` between validate and bump-version.
# Usage: scripts/qa_gate.sh [--skip]
set -euo pipefail

SKIP=false
for arg in "$@"; do
    [[ "$arg" == "--skip" ]] && SKIP=true
done

CHECKLIST="docs/TUI-QA-CHECKLIST.md"
TUI_PATHS="src/styrened/tui/"
CURRENT_VERSION=$(cat VERSION)

# ── Detect TUI changes since last release tag ────────────────────────────────
if git rev-parse "v${CURRENT_VERSION}" &>/dev/null; then
    CHANGED=$(git diff "v${CURRENT_VERSION}..HEAD" --name-only -- "$TUI_PATHS" 2>/dev/null || true)
else
    # No tag yet — treat everything as changed
    CHANGED=$(git diff HEAD --name-only -- "$TUI_PATHS" 2>/dev/null || true)
fi

if [[ -z "$CHANGED" ]]; then
    echo "  ⊘ No TUI changes detected since v${CURRENT_VERSION} — skipping visual QA gate."
    exit 0
fi

if $SKIP; then
    echo "  ⚠ --skip-qa passed. Bypassing visual QA gate."
    echo "  Changed TUI files were:"
    echo "$CHANGED" | sed 's/^/    /'
    exit 0
fi

# ── Show changed TUI files ───────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  TUI VISUAL QA GATE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  TUI files changed since v${CURRENT_VERSION}:"
echo "$CHANGED" | sed 's/^/    /'
echo ""

# ── Build diff addendum ──────────────────────────────────────────────────────
ADDENDUM=()
echo "$CHANGED" | grep -q "screens/dashboard"        && ADDENDUM+=("  • screens/dashboard.py changed → check Home panel layout")
echo "$CHANGED" | grep -q "screens/mesh_device_detail" && ADDENDUM+=("  • screens/mesh_device_detail.py changed → check peer workspace tabs")
echo "$CHANGED" | grep -q "screens/comms"            && ADDENDUM+=("  • screens/comms.py changed → check capability-gated sections")
echo "$CHANGED" | grep -q "screens/settings"         && ADDENDUM+=("  • screens/settings.py changed → check Network tab panels + save/reset")
echo "$CHANGED" | grep -q "tui/widgets"              && ADDENDUM+=("  • tui/widgets/ changed → check affected widget in its parent screen")
echo "$CHANGED" | grep -q "imperial_crt\|themes/"   && ADDENDUM+=("  • Theme/CSS changed → check color cascade across all screens")

# ── Print checklist ──────────────────────────────────────────────────────────
echo "  Core checklist: $CHECKLIST"
echo ""
echo "  CORE ITEMS (required every TUI release):"
echo "  ┌─────────────────────────────────────────────────────────────────┐"
echo "  │  Home     — NodeInfoPanel + ActivityFeedWidget, no layout break │"
echo "  │  Nodes    — Device list, peer workspace tabs, back navigation   │"
echo "  │  Comms    — Direct links, overlay sections hidden when disabled │"
echo "  │  Mail     — Inbox empty state, compose accessible              │"
echo "  │  Settings — Network tab: 5 panels, peer row add/remove, save   │"
echo "  │  Nav      — Global keybindings, screen transitions clean       │"
echo "  └─────────────────────────────────────────────────────────────────┘"
echo ""

if [[ ${#ADDENDUM[@]} -gt 0 ]]; then
    echo "  DIFF ADDENDUM (also review these based on changed files):"
    for item in "${ADDENDUM[@]}"; do
        echo "$item"
    done
    echo ""
fi

# ── Launch instructions ──────────────────────────────────────────────────────
echo "  Launch the TUI in a separate terminal:"
echo ""
echo "    .venv/bin/styrene"
echo ""
echo "  Walk through the checklist above, then return here."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Prompt ───────────────────────────────────────────────────────────────────
read -p "  Visual QA complete — proceed with release? [y/N] " -n 1 -r
echo ""
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "  Release aborted. Fix issues and re-run: just release <version>"
    exit 1
fi

echo "  ✓ Visual QA signed off. Continuing release..."
echo ""
