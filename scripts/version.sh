#!/bin/bash
# Extract version from pyproject.toml or git tags
# Supports semantic versioning with pre-release suffixes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Function to extract version from pyproject.toml or hatch
extract_from_pyproject() {
    if [ -f "$PROJECT_ROOT/pyproject.toml" ]; then
        # Try static version first
        local ver
        ver=$(grep '^version = ' "$PROJECT_ROOT/pyproject.toml" | sed 's/version = "\(.*\)"/\1/')
        if [ -n "$ver" ]; then
            echo "$ver"
            return
        fi
        # Dynamic version — read from __init__.py (same source hatchling uses)
        if [ -f "$PROJECT_ROOT/src/styrened/__init__.py" ]; then
            grep '^__version__ = ' "$PROJECT_ROOT/src/styrened/__init__.py" | sed 's/__version__ = "\(.*\)"/\1/'
        fi
    fi
}

# Function to extract version from git tags
extract_from_git() {
    cd "$PROJECT_ROOT"
    if git rev-parse --git-dir > /dev/null 2>&1; then
        # Get the most recent tag
        local tag=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
        if [ -n "$tag" ]; then
            # Strip 'v' prefix if present
            echo "$tag" | sed 's/^v//'
        fi
    fi
}

# Function to get short commit sha
get_commit_sha() {
    cd "$PROJECT_ROOT"
    if git rev-parse --git-dir > /dev/null 2>&1; then
        git rev-parse --short=7 HEAD
    fi
}

# Function to get current branch name
get_branch() {
    cd "$PROJECT_ROOT"
    if git rev-parse --git-dir > /dev/null 2>&1; then
        git rev-parse --abbrev-ref HEAD
    fi
}

# Function to check if working directory is dirty
is_dirty() {
    cd "$PROJECT_ROOT"
    if git rev-parse --git-dir > /dev/null 2>&1; then
        if [ -n "$(git status --porcelain)" ]; then
            echo "true"
        else
            echo "false"
        fi
    else
        echo "false"
    fi
}

# Main version extraction logic
main() {
    local mode="${1:-version}"

    case "$mode" in
        version)
            # Return semantic version (from VERSION file, pyproject.toml, or git tag)
            if [ -f "$PROJECT_ROOT/VERSION" ]; then
                cat "$PROJECT_ROOT/VERSION"
            else
                local version=$(extract_from_pyproject)
                if [ -z "$version" ]; then
                    version=$(extract_from_git)
                fi
                if [ -z "$version" ]; then
                    echo "0.0.0-dev"
                else
                    echo "$version"
                fi
            fi
            ;;

        tags)
            # Generate Docker image tags based on version and git state
            local version=$(main version)
            local sha=$(get_commit_sha)
            local branch=$(get_branch)
            local dirty=$(is_dirty)

            # Base tags array
            local tags=()

            # Parse version components
            if [[ "$version" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)(-(.+))?$ ]]; then
                local major="${BASH_REMATCH[1]}"
                local minor="${BASH_REMATCH[2]}"
                local patch="${BASH_REMATCH[3]}"
                local suffix="${BASH_REMATCH[5]}"

                if [ -z "$suffix" ]; then
                    # Release version: 1.2.3 -> 1.2.3, 1.2, 1, latest
                    tags+=("$version")
                    tags+=("$major.$minor")
                    tags+=("$major")
                    tags+=("latest")
                else
                    # Pre-release version: 1.2.3-rc1 -> 1.2.3-rc1, prerelease
                    tags+=("$version")
                    tags+=("prerelease")
                fi
            else
                # Non-semantic version (e.g., dev build)
                tags+=("$version")
            fi

            # Add branch-based tag if on a branch
            if [ -n "$branch" ] && [ -n "$sha" ]; then
                if [ "$branch" = "main" ] || [ "$branch" = "master" ]; then
                    tags+=("edge")
                    tags+=("$branch-$sha")
                elif [[ "$branch" =~ ^pr-([0-9]+) ]]; then
                    # PR builds
                    tags+=("pr-${BASH_REMATCH[1]}")
                    tags+=("$branch-$sha")
                else
                    tags+=("$branch-$sha")
                fi
            fi

            # Add dirty suffix if working directory has changes
            if [ "$dirty" = "true" ] && [ -n "$sha" ]; then
                tags+=("$sha-dirty")
            fi

            # Output tags (one per line)
            printf '%s\n' "${tags[@]}"
            ;;

        major)
            local version=$(main version)
            if [[ "$version" =~ ^([0-9]+) ]]; then
                echo "${BASH_REMATCH[1]}"
            fi
            ;;

        minor)
            local version=$(main version)
            if [[ "$version" =~ ^[0-9]+\.([0-9]+) ]]; then
                echo "${BASH_REMATCH[1]}"
            fi
            ;;

        patch)
            local version=$(main version)
            if [[ "$version" =~ ^[0-9]+\.[0-9]+\.([0-9]+) ]]; then
                echo "${BASH_REMATCH[1]}"
            fi
            ;;

        sha)
            get_commit_sha
            ;;

        branch)
            get_branch
            ;;

        dirty)
            is_dirty
            ;;

        *)
            echo "Usage: $0 {version|tags|major|minor|patch|sha|branch|dirty}"
            exit 1
            ;;
    esac
}

main "$@"
