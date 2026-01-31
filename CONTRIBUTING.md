# Contributing to Styrened

Thank you for your interest in contributing to Styrened. This guide covers the development workflow, testing requirements, and contribution process.

## Development Workflow

### 1. Fork and Clone

```bash
# Fork the repository on GitHub
# Clone your fork
git clone https://github.com/YOUR-USERNAME/styrened.git
cd styrened

# Add upstream remote
git remote add upstream https://github.com/styrene-lab/styrened.git
```

### 2. Set Up Development Environment

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install with development dependencies
make install

# Verify installation
python -c "import styrened; print(styrened.__version__)"
```

### 3. Create a Branch

Use descriptive branch names:

```bash
# Feature branch
git checkout -b feature/add-mesh-routing

# Bugfix branch
git checkout -b fix/reconnection-timeout

# Documentation branch
git checkout -b docs/update-deployment-guide
```

### 4. Make Changes

Follow these guidelines:

- Write clean, readable code
- Add docstrings to functions and classes
- Update tests for new functionality
- Update documentation if needed
- Keep commits focused and atomic

### 5. Commit Changes

Write clear, concise commit messages:

```bash
# Good commit messages
git commit -m "Add mesh routing algorithm"
git commit -m "Fix reconnection timeout in hub mode"
git commit -m "Update deployment guide with Kubernetes examples"

# Bad commit messages
git commit -m "Update"
git commit -m "Fix stuff"
git commit -m "WIP"
```

Commit message format:

```
<type>: <description>

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `test`: Test updates
- `refactor`: Code refactoring
- `perf`: Performance improvements
- `chore`: Maintenance tasks

### 6. Stay Synchronized

Keep your branch up to date with upstream:

```bash
# Fetch upstream changes
git fetch upstream

# Rebase on upstream main
git rebase upstream/main

# Resolve conflicts if any
git mergetool
git rebase --continue
```

### 7. Push Changes

```bash
# Push to your fork
git push origin feature/add-mesh-routing

# Force push after rebase (if needed)
git push --force-with-lease origin feature/add-mesh-routing
```

### 8. Create Pull Request

1. Go to GitHub and create a pull request
2. Fill out the PR template
3. Link related issues
4. Wait for CI validation
5. Address review feedback

## Local Testing Requirements

### Before Creating a Pull Request

Run all validation checks locally:

```bash
# Full validation (lint + typecheck + test)
make validate

# Individual checks
make lint        # Code linting
make typecheck   # Type checking
make test        # Run all tests
```

### Kubernetes Integration Tests

For changes affecting Kubernetes deployments, run integration tests:

#### Prerequisites

Install a local Kubernetes cluster:

**kind** (recommended):
```bash
# Install kind
brew install kind  # macOS
# or: https://kind.sigs.k8s.io/docs/user/quick-start/#installation

# Create cluster
kind create cluster --name styrene-test
```

**k3d** (alternative):
```bash
# Install k3d
brew install k3d  # macOS
# or: https://k3d.io/#installation

# Create cluster
k3d cluster create styrene-test
```

#### Running Tests

```bash
# Build test image
docker build -t styrened-test:latest -f tests/k8s/docker/Dockerfile .

# Load image into cluster
kind load docker-image styrened-test:latest --name styrene-test  # kind
# or
k3d image import styrened-test:latest -c styrene-test  # k3d

# Run smoke tests (fastest, ~3-5 min)
pytest tests/k8s/ -m smoke -v

# Run smoke + integration tests (~10-15 min)
pytest tests/k8s/ -m "smoke or integration" -v

# Run full suite (~30-40 min)
pytest tests/k8s/ -v --run-slow
```

#### Parallel Execution

Speed up tests with parallel execution:

```bash
# Auto-detect CPU count
pytest tests/k8s/ -m smoke -n auto

# Explicit worker count
pytest tests/k8s/ -m smoke -n 4
```

### Test Guidelines

#### Writing Tests

1. **Test Driven Development**: Write tests before implementation
2. **Test Coverage**: Aim for >80% coverage on new code
3. **Test Organization**: Group related tests in classes
4. **Test Naming**: Use descriptive names (`test_reconnects_after_hub_failure`)
5. **Test Isolation**: Each test should be independent

#### Test Markers

Use pytest markers to categorize tests:

```python
@pytest.mark.smoke         # Fast validation (<2 min)
@pytest.mark.integration   # Moderate complexity (<10 min)
@pytest.mark.comprehensive # Deep validation (<30 min)
@pytest.mark.slow          # Long-running tests (>10 min)
```

Example:

```python
import pytest

@pytest.mark.smoke
def test_basic_deployment(styrened_stack):
    """Test basic deployment succeeds."""
    pods = styrened_stack(replica_count=1, mode="standalone")
    assert len(pods) == 1

@pytest.mark.integration
def test_hub_peer_communication(styrened_stack):
    """Test hub and peer can communicate."""
    hub_pods = styrened_stack(replica_count=1, mode="hub")
    peer_pods = styrened_stack(replica_count=3, mode="peer")
    # ... test communication
```

## CI/CD Expectations

### Pull Request Validation

When you create a PR, the following checks run automatically:

1. **Build**: Docker image build (single-arch)
2. **Smoke Tests**: Fast validation tier (~10 min)
3. **Code Quality**: Linting and type checking
4. **Comment**: Results posted to PR

**Expectation**: All checks must pass before merge.

### Test Tiers in CI

| Tier | Runs On | Duration | Purpose |
|------|---------|----------|---------|
| Smoke | Every PR | ~10 min | Fast validation, critical path |
| Integration | Merge to main | ~20 min | Common scenarios |
| Comprehensive | Nightly, releases | ~60 min | Deep validation, edge cases |

### Viewing Results

```bash
# List workflow runs
gh run list

# Watch live
gh run watch

# View logs
gh run view --log

# Download artifacts
gh run download
```

### Addressing Failures

1. **Review logs**: Check workflow output for errors
2. **Reproduce locally**: Run failed tests on your machine
3. **Fix issues**: Make corrections in your branch
4. **Push updates**: CI will re-run automatically
5. **Request re-review**: After CI passes

## Release Process

### Version Bumping

Releases follow semantic versioning (MAJOR.MINOR.PATCH).

#### For Maintainers Only

1. **Update VERSION file**:
```bash
echo "0.3.0" > VERSION
```

2. **Commit version bump**:
```bash
git add VERSION
git commit -m "Bump version to 0.3.0"
```

3. **Create tag**:
```bash
git tag v0.3.0
```

4. **Push**:
```bash
git push origin main
git push origin v0.3.0
```

5. **Monitor release**:
```bash
gh run watch
```

See [RELEASE-PROCESS.md](./RELEASE-PROCESS.md) for detailed release workflow.

### Pre-releases

For release candidates and betas:

```bash
# Release candidate
echo "0.3.0-rc1" > VERSION
git tag v0.3.0-rc1

# Alpha
echo "1.0.0-alpha1" > VERSION
git tag v1.0.0-alpha1

# Beta
echo "1.0.0-beta1" > VERSION
git tag v1.0.0-beta1
```

## Code Review Checklist

### For Authors

Before requesting review:

- [ ] All tests pass locally (`make validate`)
- [ ] K8s integration tests pass (if applicable)
- [ ] Code follows project style (run `make format`)
- [ ] New code has tests (aim for >80% coverage)
- [ ] Documentation updated (docstrings, README, etc.)
- [ ] Commit messages are clear and descriptive
- [ ] PR description explains what and why
- [ ] Related issues linked

### For Reviewers

When reviewing PRs:

- [ ] Code changes align with PR description
- [ ] Tests cover new functionality
- [ ] No obvious bugs or security issues
- [ ] Code follows project conventions
- [ ] Documentation is clear and accurate
- [ ] CI checks pass
- [ ] No unnecessary dependencies added
- [ ] Performance implications considered

## Development Best Practices

### Code Style

- **Formatting**: Use `ruff format` for consistent style
- **Linting**: Fix issues reported by `ruff check`
- **Type Hints**: Add type annotations to function signatures
- **Docstrings**: Use Google-style docstrings

Example:

```python
def deploy_stack(
    replica_count: int,
    mode: str,
    rpc_enabled: bool = True,
) -> list[str]:
    """Deploy a styrened stack to Kubernetes.

    Args:
        replica_count: Number of replicas to deploy
        mode: Deployment mode (standalone, hub, peer, gateway)
        rpc_enabled: Enable RPC server (default: True)

    Returns:
        List of pod names

    Raises:
        ValueError: If mode is invalid
        TimeoutError: If deployment exceeds timeout
    """
    # Implementation
```

### Error Handling

- Use specific exception types
- Provide helpful error messages
- Clean up resources on failure
- Log errors appropriately

```python
try:
    pods = harness.deploy_stack(release_name, replica_count, mode)
    harness.wait_for_ready(pods, timeout=60)
except TimeoutError as e:
    harness.cleanup(release_name)
    raise RuntimeError(f"Deployment failed: {e}") from e
```

### Logging

- Use standard Python logging
- Include context in log messages
- Use appropriate log levels
- Avoid logging sensitive information

```python
import logging

logger = logging.getLogger(__name__)

logger.debug("Starting deployment: %s", release_name)
logger.info("Deployed %d pods in %s mode", replica_count, mode)
logger.warning("Pod %s not ready after 30s", pod_name)
logger.error("Deployment failed: %s", error)
```

### Testing

- Write tests before implementation (TDD)
- Use fixtures for common setup
- Parametrize tests for multiple scenarios
- Clean up resources after tests

```python
@pytest.fixture
def test_namespace(k8s_cluster):
    """Create unique namespace for test."""
    namespace = f"test-{uuid.uuid4().hex[:8]}"
    k8s_cluster.create_namespace(namespace)
    yield namespace
    k8s_cluster.delete_namespace(namespace)

@pytest.mark.parametrize("mode", ["standalone", "hub", "peer"])
def test_deployment_modes(styrened_stack, mode):
    """Test all deployment modes."""
    pods = styrened_stack(replica_count=1, mode=mode)
    assert len(pods) == 1
```

## Documentation

### Code Documentation

- **Modules**: Docstring at top of file
- **Classes**: Docstring describing purpose
- **Methods**: Docstring with Args, Returns, Raises
- **Complex Logic**: Inline comments explaining why

### User Documentation

Update when adding features:

- **README.md**: High-level overview and quick start
- **docs/**: Detailed guides and references
- **CHANGELOG.md**: User-facing changes (maintainers)

### Examples

Provide examples for new features:

```python
# examples/mesh_routing.py
"""Example: Setting up mesh routing between nodes."""

from styrened import MeshRouter

# Create router
router = MeshRouter(mode="hub")

# Configure routes
router.add_route("peer-1", "192.168.1.10")
router.add_route("peer-2", "192.168.1.11")

# Start routing
router.start()
```

## Communication

### Reporting Issues

When reporting bugs:

1. Check existing issues first
2. Use issue template
3. Provide minimal reproduction
4. Include version and environment
5. Attach logs if relevant

### Asking Questions

- Use GitHub Discussions for questions
- Check documentation first
- Provide context and examples
- Be respectful and patient

### Proposing Features

- Open an issue to discuss first
- Explain the use case
- Consider implementation complexity
- Be open to feedback

## Getting Help

- **Documentation**: [docs/](./docs/)
- **Examples**: [examples/](./examples/)
- **Issues**: [GitHub Issues](https://github.com/styrene-lab/styrened/issues)
- **Discussions**: [GitHub Discussions](https://github.com/styrene-lab/styrened/discussions)

## License

By contributing to Styrened, you agree that your contributions will be licensed under the project's MIT license.

## Code of Conduct

We are committed to providing a welcoming and inclusive environment. All contributors are expected to:

- Be respectful and professional
- Provide constructive feedback
- Accept constructive criticism
- Focus on what is best for the community
- Show empathy towards others

Unacceptable behavior includes:

- Harassment or discrimination
- Personal attacks or insults
- Publishing private information
- Trolling or inflammatory comments
- Other unprofessional conduct

Report violations to the project maintainers.

## Recognition

Contributors are recognized in:

- **CONTRIBUTORS.md**: All contributors listed
- **Release Notes**: Significant contributions highlighted
- **GitHub**: Contribution graph and activity

Thank you for contributing to Styrened!
