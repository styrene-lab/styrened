#!/usr/bin/env bash
# Release script — bumps version, publishes styrened AND styrene meta-package together.
# Usage: ./scripts/release.sh <version> "<commit message>"
# Example: ./scripts/release.sh 0.10.35 "feat: add cool thing"
set -euo pipefail

VERSION="${1:?Usage: release.sh <version> \"<commit message>\"}"
MESSAGE="${2:?Usage: release.sh <version> \"<commit message>\"}"

STYRENED_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYPI_DIR="$(cd "$STYRENED_DIR/../styrene-pypi" && pwd)"

echo "=== Releasing v${VERSION} ==="
echo "  styrened: ${STYRENED_DIR}"
echo "  styrene-pypi: ${PYPI_DIR}"
echo ""

# 1. Bump styrened
cd "$STYRENED_DIR"
sed -i '' "s/__version__ = \".*\"/__version__ = \"${VERSION}\"/" src/styrened/__init__.py
echo "$VERSION" > VERSION
git add -A
git commit -m "$MESSAGE"
rm -rf dist/
python -m build
twine upload dist/*
git tag "v${VERSION}"
git push origin main --tags
echo "✅ styrened ${VERSION} published"

# 2. Bump styrene-pypi
cd "$PYPI_DIR"
# Replace all version references in pyproject.toml
OLD_VERSION=$(grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
sed -i '' "s/${OLD_VERSION}/${VERSION}/g" pyproject.toml
git add -A
git commit -m "chore: bump to ${VERSION}"
rm -rf dist/
python -m build
twine upload dist/*
git tag "v${VERSION}"
git push origin main --tags
echo "✅ styrene ${VERSION} published"

echo ""
echo "=== v${VERSION} released ==="
echo "  pipx upgrade styrene  # to install"
