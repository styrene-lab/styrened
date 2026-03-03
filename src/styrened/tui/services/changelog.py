"""Changelog fetcher for the upgrade screen.

Fetches commit summaries between two version tags from GitHub,
or falls back to listing intermediate PyPI versions.
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

GITHUB_COMPARE_URL = "https://api.github.com/repos/styrene-lab/styrened/compare/v{old}...v{new}"
GITHUB_TAGS_URL = "https://api.github.com/repos/styrene-lab/styrened/tags?per_page=100"
PYPI_URL = "https://pypi.org/pypi/styrened/json"
REQUEST_TIMEOUT = 5  # seconds


@dataclass
class ChangelogEntry:
    """A single changelog item."""

    version: str
    summary: str


@dataclass
class Changelog:
    """Changelog between two versions."""

    from_version: str
    to_version: str
    entries: list[ChangelogEntry] = field(default_factory=list)
    version_count: int = 0  # Number of intermediate versions
    error: str | None = None

    @property
    def is_empty(self) -> bool:
        return len(self.entries) == 0 and self.error is None

    def format_lines(self, max_lines: int = 40) -> list[str]:
        """Format changelog as display lines.

        Args:
            max_lines: Maximum lines to return. Truncates with a summary.

        Returns:
            List of formatted strings.
        """
        if self.error:
            return [f"Could not fetch changelog: {self.error}"]

        if self.is_empty:
            return [f"v{self.from_version} → v{self.to_version} ({self.version_count} versions)"]

        lines: list[str] = []

        if self.version_count > 1:
            lines.append(
                f"{self.version_count} version(s) between "
                f"v{self.from_version} and v{self.to_version}:"
            )
            lines.append("")

        # Group entries by version for cleaner display
        current_ver = ""
        for entry in self.entries:
            if entry.version and entry.version != current_ver:
                if current_ver:
                    lines.append("")  # blank line between versions
                current_ver = entry.version
                if entry.summary:
                    lines.append(f"  v{entry.version}")
                    lines.append(f"    {entry.summary}")
                else:
                    # Version-only entry (PyPI fallback, no commit messages)
                    lines.append(f"  v{entry.version}")
            elif entry.summary:
                if entry.version:
                    lines.append(f"    {entry.summary}")
                else:
                    lines.append(f"  • {entry.summary}")

        if len(lines) > max_lines:
            kept = max_lines - 2
            omitted = len(lines) - kept
            lines = lines[:kept]
            lines.append("")
            lines.append(f"  ... and {omitted} more entries")

        return lines


def fetch_changelog(from_version: str, to_version: str) -> Changelog:
    """Fetch changelog between two versions.

    Strategy order:
    1. Bundled changelog (baked into package at build time — always works)
    2. Local git log (dev installs from git checkout)
    3. GitHub compare API (needs auth for private repos)
    4. PyPI version listing (always works, no commit messages)

    Args:
        from_version: Current version (e.g., "0.12.5").
        to_version: Target version (e.g., "0.13.7").

    Returns:
        Changelog with entries, or error message.
    """
    # Strategy 1: Bundled changelog (always available, has commit messages)
    changelog = _fetch_from_bundled(from_version, to_version)
    if changelog is not None and changelog.entries:
        return changelog

    # Strategy 2: Local git log
    changelog = _fetch_from_git_log(from_version, to_version)
    if changelog is not None and changelog.entries:
        return changelog

    # Strategy 3: GitHub compare API
    changelog = _fetch_from_github_compare(from_version, to_version)
    if changelog is not None and changelog.entries:
        return changelog

    # Strategy 4: PyPI version listing (no commit messages)
    changelog = _fetch_from_pypi_versions(from_version, to_version)
    if changelog is not None:
        return changelog

    return Changelog(
        from_version=from_version,
        to_version=to_version,
        error="Could not reach GitHub or PyPI",
    )


def _fetch_from_bundled(from_version: str, to_version: str) -> Changelog | None:
    """Read changelog from bundled data baked in at build time."""
    try:
        from packaging.version import Version

        from styrened._changelog import ENTRIES

        if not ENTRIES:
            return None

        from_v = Version(from_version)
        to_v = Version(to_version)

        entries = [
            ChangelogEntry(version=ver, summary=summary)
            for ver, summary in ENTRIES
            if from_v < Version(ver) <= to_v
        ]

        if not entries:
            return None

        return Changelog(
            from_version=from_version,
            to_version=to_version,
            entries=entries,
            version_count=len(entries),
        )

    except Exception as e:
        logger.debug(f"Bundled changelog failed: {e}")
        return None


def _fetch_from_git_log(from_version: str, to_version: str) -> Changelog | None:
    """Fetch commit messages between two version tags from local git history.

    Works when the package is installed from a git checkout or the git
    repo is available at the package source location.
    """
    import subprocess
    from pathlib import Path

    # Find the git repo — try the package source directory first
    try:
        pkg_dir = Path(__file__).resolve().parent.parent.parent.parent
        # Verify it's a git repo with the tags we need
        result = subprocess.run(
            ["git", "log", f"v{from_version}..v{to_version}", "--oneline", "--no-merges"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(pkg_dir),
        )
        if result.returncode != 0:
            return None

        lines = result.stdout.strip().splitlines()
        if not lines:
            return None

        # Also get intermediate tags to group commits by version
        tag_result = subprocess.run(
            ["git", "tag", "--list", "v*", "--sort=version:refname"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(pkg_dir),
        )
        all_tags = tag_result.stdout.strip().splitlines() if tag_result.returncode == 0 else []

        from packaging.version import Version
        from_v = Version(from_version)
        to_v = Version(to_version)
        intermediate_tags = [
            t for t in all_tags
            if t.startswith("v") and from_v < Version(t[1:]) <= to_v
        ]

        # Build entries grouped by tag
        entries: list[ChangelogEntry] = []

        if intermediate_tags:
            # Get commits for each version range
            prev_tag = f"v{from_version}"
            for tag in intermediate_tags:
                ver = tag[1:]  # strip 'v'
                commit_result = subprocess.run(
                    ["git", "log", f"{prev_tag}..{tag}", "--oneline", "--no-merges"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=str(pkg_dir),
                )
                if commit_result.returncode == 0:
                    tag_commits = commit_result.stdout.strip().splitlines()
                    for line in tag_commits:
                        # Strip hash prefix
                        summary = line.split(" ", 1)[1] if " " in line else line
                        summary = summary.strip()
                        if not summary or "bump version" in summary.lower():
                            continue
                        entries.append(ChangelogEntry(version=ver, summary=summary))
                prev_tag = tag
        else:
            # No intermediate tags — just list commits
            for line in lines:
                summary = line.split(" ", 1)[1] if " " in line else line
                summary = summary.strip()
                if not summary or "bump version" in summary.lower():
                    continue
                entries.append(ChangelogEntry(version="", summary=summary))

        return Changelog(
            from_version=from_version,
            to_version=to_version,
            entries=entries,
            version_count=len(intermediate_tags) or 1,
        )

    except Exception as e:
        logger.debug(f"Git log changelog failed: {e}")
        return None


def _fetch_from_github_compare(from_version: str, to_version: str) -> Changelog | None:
    """Fetch commit messages between two version tags from GitHub."""
    url = GITHUB_COMPARE_URL.format(old=from_version, new=to_version)
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "styrened-changelog",
            },
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read())

        commits = data.get("commits", [])
        if not commits:
            return None

        # Group commits by version tag if possible, otherwise list individually.
        # For simplicity, extract the first line of each commit message.
        entries: list[ChangelogEntry] = []
        seen_summaries: set[str] = set()

        for commit in reversed(commits):  # oldest first
            msg = commit.get("commit", {}).get("message", "")
            # First line only
            summary = msg.split("\n")[0].strip()
            if not summary:
                continue

            # Skip merge commits and version bumps
            if summary.startswith("Merge "):
                continue

            # Deduplicate
            if summary in seen_summaries:
                continue
            seen_summaries.add(summary)

            # Try to extract version from "chore: bump version to X.Y.Z" patterns
            version = ""
            if "bump version" in summary.lower():
                continue  # Skip version bump commits entirely

            entries.append(ChangelogEntry(version="", summary=summary))

        # Count intermediate versions from tag names in the compare
        total_commits = data.get("total_commits", len(commits))

        return Changelog(
            from_version=from_version,
            to_version=to_version,
            entries=entries,
            version_count=total_commits,
        )

    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        logger.debug(f"GitHub compare failed: {e}")
        return None
    except Exception as e:
        logger.debug(f"GitHub compare parse error: {e}")
        return None


def _fetch_from_pypi_versions(from_version: str, to_version: str) -> Changelog | None:
    """List intermediate versions between from and to from PyPI."""
    try:
        from packaging.version import Version

        req = urllib.request.Request(
            PYPI_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "styrened-changelog",
            },
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read())

        all_versions = sorted(
            [v for v in data.get("releases", {}).keys() if not Version(v).is_prerelease],
            key=Version,
        )

        from_v = Version(from_version)
        to_v = Version(to_version)

        intermediate = [v for v in all_versions if from_v < Version(v) <= to_v]

        entries = [
            ChangelogEntry(version=v, summary="")
            for v in intermediate
        ]

        return Changelog(
            from_version=from_version,
            to_version=to_version,
            entries=entries,
            version_count=len(intermediate),
        )

    except Exception as e:
        logger.debug(f"PyPI version listing failed: {e}")
        return None
