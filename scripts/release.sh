#!/usr/bin/env bash
# Release script — bumps version, publishes styrened AND styrene meta-package together.
# Usage: ./scripts/release.sh <version> "<commit message>" [--dry-run]
# Example: ./scripts/release.sh 0.10.38 "feat: add cool thing"
set -euo pipefail

VERSION="${1:?Usage: release.sh <version> \"<commit message>\" [--dry-run]}"
MESSAGE="${2:?Usage: release.sh <version> \"<commit message>\" [--dry-run]}"
DRY_RUN="${3:-}"

STYRENED_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYPI_DIR="$(cd "$STYRENED_DIR/../styrene-pypi" && pwd)"

# --- Validation ---

# Semver-ish check (X.Y.Z with optional pre-release)
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+'; then
    echo "ERROR: Version '$VERSION' doesn't look like semver (expected X.Y.Z)" >&2
    exit 1
fi

# Check we're on main
BRANCH="$(cd "$STYRENED_DIR" && git branch --show-current)"
if [[ "$BRANCH" != "main" ]]; then
    echo "ERROR: Not on main branch (on '$BRANCH')" >&2
    exit 1
fi

# Check styrene-pypi is clean (styrened changes are expected — we commit them)
if ! (cd "$PYPI_DIR" && git diff --quiet && git diff --cached --quiet); then
    echo "ERROR: styrene-pypi working tree is not clean" >&2
    exit 1
fi

# Check version is greater than current
CURRENT_VERSION="$(grep '__version__' "$STYRENED_DIR/src/styrened/__init__.py" | sed 's/.*"\(.*\)".*/\1/')"
if [[ "$VERSION" == "$CURRENT_VERSION" ]]; then
    echo "ERROR: Version $VERSION is already the current version" >&2
    exit 1
fi

echo "=== Releasing v${VERSION} ==="
echo "  styrened: ${STYRENED_DIR}"
echo "  styrene-pypi: ${PYPI_DIR}"
echo "  current: ${CURRENT_VERSION}"
if [[ "$DRY_RUN" == "--dry-run" ]]; then
    echo "  MODE: DRY RUN (no publish, no push)"
fi
echo ""

# 1. Bump styrened
cd "$STYRENED_DIR"
sed -i '' "s/__version__ = \".*\"/__version__ = \"${VERSION}\"/" src/styrened/__init__.py
echo "$VERSION" > VERSION
git add -A
git commit -m "$MESSAGE"
rm -rf dist/
"$STYRENED_DIR/.venv/bin/python" -m build

if [[ "$DRY_RUN" == "--dry-run" ]]; then
    echo "[DRY RUN] Would upload styrened ${VERSION} to PyPI"
    echo "[DRY RUN] Would tag v${VERSION} and push"
else
    "$STYRENED_DIR/.venv/bin/twine" upload dist/*
    git tag "v${VERSION}"
    git push origin main --tags
fi
echo "✅ styrened ${VERSION} $([ "$DRY_RUN" = "--dry-run" ] && echo "(dry run)" || echo "published")"

# 2. Bump styrene-pypi
cd "$PYPI_DIR"
OLD_VERSION=$(grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
sed -i '' "s/${OLD_VERSION}/${VERSION}/g" pyproject.toml
git add -A
git commit -m "chore: bump to ${VERSION}"
rm -rf dist/
"$STYRENED_DIR/.venv/bin/python" -m build

if [[ "$DRY_RUN" == "--dry-run" ]]; then
    echo "[DRY RUN] Would upload styrene ${VERSION} to PyPI"
    echo "[DRY RUN] Would tag v${VERSION} and push"
    # Revert both repos since we didn't push
    cd "$STYRENED_DIR" && git reset --soft HEAD~1 && git checkout -- .
    cd "$PYPI_DIR" && git reset --soft HEAD~1 && git checkout -- .
    echo ""
    echo "=== DRY RUN COMPLETE — no changes published ==="
else
    "$STYRENED_DIR/.venv/bin/twine" upload dist/*
    git tag "v${VERSION}"
    git push origin main --tags
    echo "✅ styrene ${VERSION} published"
    echo ""
    echo "=== v${VERSION} released ==="
    echo "  pipx upgrade styrene  # to install"
fi
