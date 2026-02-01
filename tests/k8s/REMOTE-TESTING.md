# Remote Cluster Testing with GHCR Images

Guide for running styrened K8s integration tests on remote clusters (like brutus) using images from GitHub Container Registry.

## Overview

Instead of building and loading images locally, you can pull pre-built images from GHCR:
- **Test images**: `ghcr.io/styrene-lab/styrened-test:latest` (nightly builds)
- **Production images**: `ghcr.io/styrene-lab/styrened:latest` (releases)

This is useful for:
- Testing on remote clusters (e.g., brutus k3s cluster)
- Using CI-built images without rebuilding locally
- Testing specific versions or commits
- ARM64 clusters (Raspberry Pi, etc.)

## Prerequisites

### 1. GitHub Authentication

Ensure you have GitHub CLI authenticated with `read:packages` scope:

```bash
# Check current auth status
gh auth status

# Should show:
# Token scopes: 'read:packages', 'write:packages', ...
```

If not authenticated:
```bash
gh auth login
# Select HTTPS, authenticate, and enable read:packages scope
```

### 2. Kubernetes Cluster Access

Verify kubectl is configured for your target cluster:

```bash
# Check current context
kubectl config current-context

# Should show: k3d-brutus, kind-test, etc.

# Test connectivity
kubectl get nodes
```

## Quick Start

### One-Command Setup

```bash
# Create secret, deploy from GHCR, run smoke tests
make test-k8s-remote
```

This will:
1. Create `ghcr-secret` ImagePullSecret in `styrene-test` namespace
2. Deploy Helm chart using GHCR images
3. Run smoke tests against the deployment

### Manual Steps

If you prefer to run steps individually:

```bash
# 1. Create ImagePullSecret for GHCR
make create-ghcr-secret

# 2. Deploy using GHCR images
make helm-install-ghcr

# 3. Run tests
make test-k8s-run

# 4. Cleanup
make helm-uninstall
```

## ImagePullSecret Management

### Create Secret

```bash
# Create secret in styrene-test namespace
make create-ghcr-secret
```

This creates a secret named `ghcr-secret` using your GitHub credentials from:
- `GITHUB_TOKEN` env var (if set), or
- `gh auth token` output (gh CLI)

**Environment variables** (optional):
```bash
export GITHUB_TOKEN=ghp_xxxxx      # Override gh CLI token
export GITHUB_ACTOR=cwilson613     # Override username
export GITHUB_EMAIL=you@email.com  # Override email
```

### Verify Secret

```bash
# Check if secret exists and looks valid
make verify-ghcr-secret
```

Output:
```
Secret exists
Secret details:
  Size: 342 bytes (looks valid)
```

### Delete Secret

```bash
# Remove secret from namespace
make delete-ghcr-secret
```

## Deployment Options

### Option 1: Latest Nightly Test Image

```bash
make create-ghcr-secret
make helm-install-ghcr
```

Uses `ghcr.io/styrene-lab/styrened-test:latest` (from nightly builds).

### Option 2: Specific Version

```bash
make create-ghcr-secret

# Deploy specific version
helm upgrade --install styrene-test tests/k8s/helm/styrened-test \
  -n styrene-test --create-namespace \
  --set image.repository=ghcr.io/styrene-lab/styrened-test \
  --set image.tag=0.2.0 \
  --set image.pullPolicy=Always \
  --set imagePullSecrets[0].name=ghcr-secret
```

### Option 3: Production Image

```bash
make create-ghcr-secret

# Deploy production image
helm upgrade --install styrene-test tests/k8s/helm/styrened-test \
  -n styrene-test --create-namespace \
  --set image.repository=ghcr.io/styrene-lab/styrened \
  --set image.tag=latest \
  --set image.pullPolicy=Always \
  --set imagePullSecrets[0].name=ghcr-secret
```

### Option 4: Specific Commit

```bash
# Use commit SHA from CI build
helm upgrade --install styrene-test tests/k8s/helm/styrened-test \
  -n styrene-test --create-namespace \
  --set image.repository=ghcr.io/styrene-lab/styrened-test \
  --set image.tag=be0ec70 \
  --set image.pullPolicy=Always \
  --set imagePullSecrets[0].name=ghcr-secret
```

## Remote Cluster Examples

### Brutus K3s Cluster

```bash
# 1. Set kubectl context
kubectl config use-context k3s-brutus

# 2. Verify connectivity
kubectl get nodes

# 3. Run remote test workflow
make test-k8s-remote

# 4. Monitor pods
kubectl get pods -n styrene-test -w

# 5. Check logs
kubectl logs -l app.kubernetes.io/instance=styrene-test -n styrene-test

# 6. Cleanup
make helm-uninstall
```

### K3d Local Cluster

```bash
# Create k3d cluster
k3d cluster create brutus-test

# Run tests with GHCR images
make test-k8s-remote

# Cleanup
make helm-uninstall
k3d cluster delete brutus-test
```

## Troubleshooting

### ImagePullBackOff Errors

**Symptom:**
```bash
kubectl get pods -n styrene-test
# NAME              READY   STATUS             RESTARTS   AGE
# styrene-test-0    0/1     ImagePullBackOff   0          30s
```

**Check secret exists:**
```bash
make verify-ghcr-secret
```

**Check pod events:**
```bash
kubectl describe pod styrene-test-0 -n styrene-test | grep -A 10 Events
```

**Common causes:**
1. Secret doesn't exist → Run `make create-ghcr-secret`
2. Wrong secret name → Verify `imagePullSecrets[0].name=ghcr-secret`
3. Token expired → Run `gh auth refresh && make create-ghcr-secret`
4. Wrong registry → Should be `ghcr.io/styrene-lab/...`

**Fix:**
```bash
# Recreate secret
make delete-ghcr-secret
make create-ghcr-secret

# Redeploy
make helm-install-ghcr
```

### Authentication Failed

**Error in pod events:**
```
Failed to pull image: unauthorized: authentication required
```

**Verify token has packages scope:**
```bash
gh auth status
# Should show: Token scopes: '...read:packages...'
```

**Refresh authentication:**
```bash
gh auth refresh -h github.com -s read:packages,write:packages
make create-ghcr-secret
```

### Secret Not Found

**Error:**
```
Error from server (NotFound): secrets "ghcr-secret" not found
```

**Solution:**
```bash
make create-ghcr-secret
```

### Wrong Namespace

Ensure you're using the `styrene-test` namespace:

```bash
# Check current namespace
kubectl config view --minify | grep namespace

# Set namespace
kubectl config set-context --current --namespace=styrene-test
```

### Image Not Found

**Error:**
```
Failed to pull image "ghcr.io/styrene-lab/styrened-test:latest":
manifest unknown: manifest unknown
```

**Verify image exists:**
```bash
# Check available tags on GitHub
gh api /orgs/styrene-lab/packages/container/styrened-test/versions

# Or browse: https://github.com/orgs/styrene-lab/packages
```

**Use a known tag:**
```bash
# Try with version tag instead of latest
helm upgrade --install styrene-test tests/k8s/helm/styrened-test \
  -n styrene-test --create-namespace \
  --set image.repository=ghcr.io/styrene-lab/styrened-test \
  --set image.tag=0.2.0 \
  --set image.pullPolicy=Always \
  --set imagePullSecrets[0].name=ghcr-secret
```

## Security Considerations

### Secret Lifecycle

The ImagePullSecret contains your GitHub token. Handle it securely:

**Best practices:**
- Create secret per namespace/cluster
- Use tokens with minimum required scopes (`read:packages`)
- Rotate tokens periodically
- Delete secrets when not in use

**Rotation:**
```bash
# Generate new token on GitHub
gh auth refresh -h github.com -s read:packages

# Recreate secret with new token
make delete-ghcr-secret
make create-ghcr-secret
```

### Scope Limitation

Only grant `read:packages` scope for pulling images:

```bash
# Check current scopes
gh auth status | grep "Token scopes"

# Refresh with minimal scopes
gh auth refresh -h github.com -s read:packages
```

### Cluster-Specific Secrets

For production clusters, create dedicated secrets:

```bash
# Create secret in production namespace
kubectl create secret docker-registry ghcr-prod-secret \
  --docker-server=ghcr.io \
  --docker-username=cwilson613 \
  --docker-password=$PROD_GITHUB_TOKEN \
  -n production
```

## Advanced Usage

### Multiple Namespaces

Create secrets in multiple namespaces:

```bash
# Create in custom namespace
kubectl create namespace my-test
kubectl create secret docker-registry ghcr-secret \
  --docker-server=ghcr.io \
  --docker-username=$(gh api user -q .login) \
  --docker-password=$(gh auth token) \
  -n my-test

# Deploy to custom namespace
helm upgrade --install my-release tests/k8s/helm/styrened-test \
  -n my-test \
  --set image.repository=ghcr.io/styrene-lab/styrened-test \
  --set image.tag=latest \
  --set image.pullPolicy=Always \
  --set imagePullSecrets[0].name=ghcr-secret
```

### ServiceAccount with ImagePullSecrets

For long-running deployments, attach secret to ServiceAccount:

```bash
# Create ServiceAccount
kubectl create serviceaccount styrened-sa -n styrene-test

# Patch to add imagePullSecrets
kubectl patch serviceaccount styrened-sa \
  -n styrene-test \
  -p '{"imagePullSecrets": [{"name": "ghcr-secret"}]}'

# Use in Helm values
helm upgrade --install styrene-test tests/k8s/helm/styrened-test \
  -n styrene-test \
  --set serviceAccount.create=false \
  --set serviceAccount.name=styrened-sa \
  --set image.repository=ghcr.io/styrene-lab/styrened-test \
  --set image.tag=latest
```

### CI/CD Integration

For GitHub Actions on self-hosted runners:

```yaml
# .github/workflows/remote-test.yml
- name: Create ImagePullSecret
  run: |
    kubectl create namespace styrene-test || true
    kubectl create secret docker-registry ghcr-secret \
      --docker-server=ghcr.io \
      --docker-username=${{ github.actor }} \
      --docker-password=${{ secrets.GITHUB_TOKEN }} \
      -n styrene-test \
      --dry-run=client -o yaml | kubectl apply -f -

- name: Deploy and test
  run: make test-k8s-remote
```

## Comparison: Local vs Remote Testing

| Aspect | Local (pre-loaded images) | Remote (GHCR images) |
|--------|---------------------------|----------------------|
| **Setup** | Build + load image | Create ImagePullSecret |
| **Time** | ~2-3 min (build + load) | ~30 sec (pull only) |
| **Bandwidth** | Low (local transfer) | Higher (registry pull) |
| **Reproducibility** | Local build may differ | Exact CI-built images |
| **Use case** | Development iteration | Testing releases/CI builds |
| **Multi-arch** | Requires QEMU emulation | Native arch from GHCR |

## Quick Reference

```bash
# Setup and test
make test-k8s-remote           # Full workflow (create secret, deploy, test)

# Secret management
make create-ghcr-secret        # Create ImagePullSecret
make verify-ghcr-secret        # Verify secret exists
make delete-ghcr-secret        # Delete secret

# Deployment
make helm-install-ghcr         # Deploy using GHCR images
make helm-install              # Deploy using local images
make helm-uninstall            # Remove deployment

# Testing
make test-k8s-run              # Run tests (assumes deployed)
make test-k8s-local            # Full local workflow (build, load, test)

# Status
kubectl get pods -n styrene-test
kubectl logs -f -l app.kubernetes.io/instance=styrene-test -n styrene-test
kubectl describe pod styrene-test-0 -n styrene-test
```

## See Also

- [QUICK-START.md](QUICK-START.md) - Quick start guide for K8s testing
- [README.md](README.md) - Complete K8s testing documentation
- [DOCKER.md](../../DOCKER.md) - Docker build pipeline documentation
