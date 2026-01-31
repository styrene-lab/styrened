# Release Process

Step-by-step guide for creating releases, managing versions, and handling hotfixes.

## Overview

Styrened follows semantic versioning (MAJOR.MINOR.PATCH) with support for pre-release suffixes.

```
Version Format: MAJOR.MINOR.PATCH[-SUFFIX]

Examples:
  0.2.0         # Stable release
  0.2.1         # Patch release
  0.3.0-rc1     # Release candidate
  1.0.0-alpha1  # Alpha release
  1.0.0-beta2   # Beta release
```

## Release Workflow

### Standard Release (0.3.0)

#### 1. Pre-Release Checklist

- [ ] All planned features merged to `main`
- [ ] All tests passing in CI
- [ ] Documentation updated
- [ ] CHANGELOG.md drafted (if maintained)
- [ ] No critical bugs in issue tracker
- [ ] Smoke tests pass locally

#### 2. Version Bump

Update the VERSION file:

```bash
# Set version
echo "0.3.0" > VERSION

# Verify
cat VERSION
# Output: 0.3.0
```

#### 3. Commit Version Bump

Create a dedicated commit for the version change:

```bash
# Add VERSION file
git add VERSION

# Commit with clear message
git commit -m "Bump version to 0.3.0"

# Push to main
git push origin main
```

#### 4. Create Git Tag

Tag the release with `v` prefix:

```bash
# Create annotated tag
git tag -a v0.3.0 -m "Release v0.3.0"

# Verify tag
git tag -l "v0.3.0"

# Show tag details
git show v0.3.0
```

#### 5. Push Tag

Pushing the tag triggers the release workflow:

```bash
# Push tag
git push origin v0.3.0

# Verify tag pushed
git ls-remote --tags origin | grep v0.3.0
```

#### 6. Monitor Release Workflow

The `release.yml` workflow will:
- Build multi-arch images (amd64, arm64)
- Run full test suite (smoke + integration + comprehensive)
- Generate changelog from commits
- Create GitHub release
- Push Docker images to registry

Monitor progress:

```bash
# Watch workflow
gh run watch

# View logs
gh run view --log

# Check status
gh run list --workflow=release.yml
```

#### 7. Verify Release

Once workflow completes:

```bash
# View release on GitHub
gh release view v0.3.0

# Pull Docker image
docker pull ghcr.io/styrene-lab/styrened:0.3.0

# Verify image tags
docker pull ghcr.io/styrene-lab/styrened:0.3
docker pull ghcr.io/styrene-lab/styrened:0
docker pull ghcr.io/styrene-lab/styrened:latest

# Test image
docker run --rm ghcr.io/styrene-lab/styrened:0.3.0 styrened --version
```

#### 8. Post-Release Tasks

- [ ] Announce release (GitHub Discussions, etc.)
- [ ] Update documentation site (if applicable)
- [ ] Close milestone (if using milestones)
- [ ] Update project board (if using projects)
- [ ] Monitor for critical issues

### Release Candidate (0.3.0-rc1)

Use release candidates to gather feedback before final release.

#### 1. Version Bump

```bash
# Set RC version
echo "0.3.0-rc1" > VERSION

# Commit
git add VERSION
git commit -m "Release candidate 0.3.0-rc1"
git push origin main
```

#### 2. Create Tag

```bash
# Create tag
git tag -a v0.3.0-rc1 -m "Release candidate 0.3.0-rc1"

# Push tag
git push origin v0.3.0-rc1
```

#### 3. Verify RC Release

```bash
# View release (marked as pre-release)
gh release view v0.3.0-rc1

# Pull image
docker pull ghcr.io/styrene-lab/styrened:0.3.0-rc1
docker pull ghcr.io/styrene-lab/styrened:prerelease
```

**Note**: RC releases:
- Marked as "pre-release" on GitHub
- Do NOT update `:latest` tag
- Use `:prerelease` tag instead

#### 4. Testing Period

- Deploy RC to test environment
- Collect feedback from testers
- Monitor for issues
- Fix critical bugs

#### 5. Subsequent RCs (if needed)

If issues found:

```bash
# Create RC2
echo "0.3.0-rc2" > VERSION
git add VERSION
git commit -m "Release candidate 0.3.0-rc2"
git tag -a v0.3.0-rc2 -m "Release candidate 0.3.0-rc2"
git push origin main
git push origin v0.3.0-rc2
```

#### 6. Final Release

Once RC testing passes:

```bash
# Create final release
echo "0.3.0" > VERSION
git add VERSION
git commit -m "Bump version to 0.3.0"
git tag -a v0.3.0 -m "Release v0.3.0"
git push origin main
git push origin v0.3.0
```

### Hotfix Release (0.2.1)

For critical bugs in production releases.

#### 1. Create Hotfix Branch

Branch from the release tag:

```bash
# Checkout release tag
git checkout v0.2.0

# Create hotfix branch
git checkout -b hotfix/0.2.1

# Verify branch
git branch
```

#### 2. Fix the Issue

```bash
# Make fixes
# ... edit files ...

# Add tests for the fix
# ... add tests ...

# Run tests locally
make validate

# Commit fix
git add .
git commit -m "Fix critical connection timeout in hub mode"
```

#### 3. Version Bump

```bash
# Update version
echo "0.2.1" > VERSION

# Commit version bump
git add VERSION
git commit -m "Bump version to 0.2.1"
```

#### 4. Create Tag

```bash
# Tag hotfix
git tag -a v0.2.1 -m "Hotfix v0.2.1 - Fix connection timeout"

# Push branch and tag
git push origin hotfix/0.2.1
git push origin v0.2.1
```

#### 5. Monitor Release

```bash
# Watch workflow
gh run watch

# Verify release
gh release view v0.2.1
```

#### 6. Merge Back to Main

**Important**: Merge hotfix back to avoid regression.

```bash
# Checkout main
git checkout main

# Pull latest
git pull origin main

# Merge hotfix (no fast-forward)
git merge --no-ff hotfix/0.2.1

# Push to main
git push origin main

# Delete hotfix branch
git branch -d hotfix/0.2.1
git push origin --delete hotfix/0.2.1
```

#### 7. Verify Integration

```bash
# Verify main has fix
git log --oneline | head -10

# Run tests on main
make validate
```

## Version Bumping Guide

### When to Bump MAJOR (X.0.0)

- Breaking API changes
- Incompatible configuration changes
- Major architecture changes
- Removal of deprecated features

Example: 0.9.0 → 1.0.0

### When to Bump MINOR (0.X.0)

- New features (backward compatible)
- New deployment modes
- Significant improvements
- Deprecation of features (but not removal)

Example: 0.2.0 → 0.3.0

### When to Bump PATCH (0.0.X)

- Bug fixes
- Security patches
- Documentation updates
- Performance improvements (no API changes)

Example: 0.2.0 → 0.2.1

### Pre-Release Suffixes

- `-rc1`, `-rc2`: Release candidates (feature complete, testing)
- `-beta1`, `-beta2`: Beta releases (feature complete, may have bugs)
- `-alpha1`, `-alpha2`: Alpha releases (incomplete, experimental)

## Tagging Conventions

### Tag Format

```
v<MAJOR>.<MINOR>.<PATCH>[-SUFFIX]

Examples:
  v0.2.0
  v0.2.1
  v0.3.0-rc1
  v1.0.0-alpha1
```

### Annotated Tags

Always use annotated tags (not lightweight):

```bash
# Good: Annotated tag
git tag -a v0.3.0 -m "Release v0.3.0"

# Bad: Lightweight tag
git tag v0.3.0
```

### Tag Messages

Use descriptive messages:

```bash
# Good messages
git tag -a v0.3.0 -m "Release v0.3.0 - Mesh routing support"
git tag -a v0.2.1 -m "Hotfix v0.2.1 - Fix connection timeout"
git tag -a v0.3.0-rc1 -m "Release candidate 0.3.0-rc1"

# Bad messages
git tag -a v0.3.0 -m "v0.3.0"
git tag -a v0.3.0 -m "Release"
```

## Creating GitHub Releases

Releases are created automatically by CI, but you can also create manually:

### Via GitHub CLI

```bash
# Create release
gh release create v0.3.0 \
  --title "Release v0.3.0" \
  --notes "See CHANGELOG.md for details"

# Create pre-release
gh release create v0.3.0-rc1 \
  --title "Release Candidate v0.3.0-rc1" \
  --notes "Testing release for 0.3.0" \
  --prerelease

# Upload artifacts
gh release upload v0.3.0 dist/*.tar.gz
```

### Via GitHub Web UI

1. Go to repository Releases page
2. Click "Draft a new release"
3. Select tag (v0.3.0)
4. Set release title
5. Write release notes
6. Check "Set as a pre-release" if RC/alpha/beta
7. Click "Publish release"

## Rollback Procedures

### Reverting a Release

If a release has critical issues:

#### 1. Mark Release as Broken

```bash
# Edit release on GitHub
gh release edit v0.3.0 --notes "⚠️ **DO NOT USE** - Critical bug, use v0.2.0 instead"

# Mark as pre-release (hides from "latest")
gh release edit v0.3.0 --prerelease
```

#### 2. Delete Registry Images (if necessary)

```bash
# Delete specific version tag (requires package:delete permission)
# This is destructive - only for critical security issues

# Delete using GitHub web UI:
# Go to Packages → styrened → Package settings → Manage versions → Delete
```

#### 3. Create Hotfix

Follow hotfix process to release corrected version:

```bash
# Create hotfix from previous good release
git checkout v0.2.0
git checkout -b hotfix/0.3.1

# Apply fixes
# ... make changes ...

# Release 0.3.1
echo "0.3.1" > VERSION
git add VERSION
git commit -m "Bump version to 0.3.1 - Fix critical issues from 0.3.0"
git tag -a v0.3.1 -m "Hotfix v0.3.1 - Replaces broken v0.3.0"
git push origin hotfix/0.3.1
git push origin v0.3.1
```

#### 4. Update Documentation

```bash
# Update README if needed
# Add note in CHANGELOG about broken release
# Announce rollback to users
```

### Rolling Back Kubernetes Deployments

If users deployed broken release:

```bash
# Provide rollback instructions
kubectl set image deployment/styrened \
  styrened=ghcr.io/styrene-lab/styrened:0.2.0

# Or via Helm
helm upgrade styrened styrened/styrened \
  --set image.tag=0.2.0 \
  --reuse-values
```

## Post-Release Validation

### Image Verification

```bash
# Pull all tag variants
docker pull ghcr.io/styrene-lab/styrened:0.3.0
docker pull ghcr.io/styrene-lab/styrened:0.3
docker pull ghcr.io/styrene-lab/styrened:0
docker pull ghcr.io/styrene-lab/styrened:latest

# Verify all point to same image
docker images --digests | grep styrened

# Test image
docker run --rm ghcr.io/styrene-lab/styrened:0.3.0 styrened --version
```

### Multi-Arch Verification

```bash
# Check manifest for multi-arch
docker manifest inspect ghcr.io/styrene-lab/styrened:0.3.0

# Should show both architectures
# - linux/amd64
# - linux/arm64
```

### Test Deployment

Deploy to test environment:

```bash
# Deploy to test cluster
kubectl apply -f examples/kubernetes/deployment.yaml

# Verify pods running
kubectl get pods -l app=styrened

# Check logs
kubectl logs -l app=styrened

# Run smoke tests
pytest tests/k8s/ -m smoke -v
```

## Changelog Management

### Automatic Changelog

The release workflow generates changelog from commit messages:

```bash
# Commits since last tag
git log v0.2.0..v0.3.0 --pretty=format:"- %s (%h)"
```

### Manual CHANGELOG.md

If maintaining manual changelog:

```markdown
# Changelog

## [0.3.0] - 2026-01-26

### Added
- Mesh routing algorithm
- Support for gateway mode
- RPC batching for improved performance

### Changed
- Updated Reticulum to 0.8.0
- Improved reconnection logic

### Fixed
- Hub connection timeout
- Memory leak in announcement handler

### Deprecated
- Legacy transport mode (use gateway mode instead)

## [0.2.0] - 2026-01-15

...
```

Update before release:

```bash
# Edit CHANGELOG.md
vim CHANGELOG.md

# Commit
git add CHANGELOG.md
git commit -m "Update CHANGELOG for v0.3.0"
git push origin main
```

## Common Issues

### Tag Already Exists

```bash
# Error: tag already exists

# Solution 1: Delete local tag
git tag -d v0.3.0
git tag -a v0.3.0 -m "Release v0.3.0"

# Solution 2: Delete remote tag
git push --delete origin v0.3.0
git push origin v0.3.0
```

### Release Workflow Fails

```bash
# Check workflow status
gh run list --workflow=release.yml

# View failure logs
gh run view <run-id> --log

# Common issues:
# - Test failures: Fix tests and create new RC
# - Registry auth: Check GITHUB_TOKEN permissions
# - Build errors: Test build locally first
```

### Wrong Version Tagged

```bash
# Delete wrong tag
git tag -d v0.3.0
git push --delete origin v0.3.0

# Create correct tag
git tag -a v0.3.0 -m "Release v0.3.0"
git push origin v0.3.0
```

### Pre-release Marked as Latest

```bash
# Edit release to mark as pre-release
gh release edit v0.3.0-rc1 --prerelease

# Or via web UI:
# Edit release → Check "Set as a pre-release" → Update release
```

## Release Checklist

### Before Release

- [ ] All planned features merged
- [ ] All tests passing
- [ ] Documentation updated
- [ ] CHANGELOG updated (if maintained)
- [ ] No blocking issues
- [ ] Version bumped in VERSION file
- [ ] Version commit pushed to main

### Creating Release

- [ ] Tag created with `v` prefix
- [ ] Tag pushed to origin
- [ ] Release workflow triggered
- [ ] Workflow completed successfully
- [ ] GitHub release created
- [ ] Docker images pushed

### After Release

- [ ] Images verified (all tags)
- [ ] Multi-arch manifest checked
- [ ] Test deployment successful
- [ ] Release announced
- [ ] Documentation site updated (if applicable)
- [ ] Monitoring for issues

## Quick Reference

### Version Commands

```bash
# Get current version
cat VERSION

# Update version
echo "0.3.0" > VERSION

# Extract from git
./scripts/version.sh version

# Get all tags
./scripts/version.sh tags
```

### Git Tag Commands

```bash
# List tags
git tag -l

# Create annotated tag
git tag -a v0.3.0 -m "Release v0.3.0"

# Delete local tag
git tag -d v0.3.0

# Delete remote tag
git push --delete origin v0.3.0

# Push tag
git push origin v0.3.0

# Checkout tag
git checkout v0.3.0
```

### GitHub Release Commands

```bash
# List releases
gh release list

# View release
gh release view v0.3.0

# Create release
gh release create v0.3.0

# Edit release
gh release edit v0.3.0 --notes "Updated notes"

# Delete release
gh release delete v0.3.0
```

### Docker Image Commands

```bash
# Pull image
docker pull ghcr.io/styrene-lab/styrened:0.3.0

# List local images
docker images | grep styrened

# Inspect manifest
docker manifest inspect ghcr.io/styrene-lab/styrened:0.3.0

# Test image
docker run --rm ghcr.io/styrene-lab/styrened:0.3.0 styrened --version
```

## Release Timeline Example

### Standard Release (0.3.0)

| Day | Activity | Duration |
|-----|----------|----------|
| D-7 | Feature freeze | - |
| D-5 | RC1 released | - |
| D-4 | Testing period | 3 days |
| D-2 | RC2 (if needed) | - |
| D-1 | Final testing | 1 day |
| D-0 | Release v0.3.0 | ~2 hours |
| D+1 | Monitor production | Ongoing |

### Hotfix Release (0.2.1)

| Time | Activity | Duration |
|------|----------|----------|
| T+0h | Critical bug reported | - |
| T+1h | Investigation complete | 1 hour |
| T+2h | Fix developed and tested | 1 hour |
| T+3h | Hotfix branch created | 10 min |
| T+4h | v0.2.1 released | 2 hours |
| T+5h | Fix verified in prod | 1 hour |
| T+6h | Merged back to main | 30 min |

## References

- [BUILD-SYSTEM.md](./BUILD-SYSTEM.md) - Build automation details
- [CONTRIBUTING.md](./CONTRIBUTING.md) - Contribution guidelines
- [Semantic Versioning](https://semver.org/) - Version numbering
- [GitHub Releases](https://docs.github.com/en/repositories/releasing-projects-on-github) - Release documentation
