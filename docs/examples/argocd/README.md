# ArgoCD Integration Examples

Reference examples for deploying styrened to production via ArgoCD on the brutus K3s cluster.

**NOT FOR PRODUCTION USE YET** - Styrened is under active development and not stable enough for production deployment. These examples are for future reference when the project reaches production readiness.

## Contents

- `application.yaml` - ArgoCD Application manifest
- `values.yaml` - Production values override
- This README with deployment instructions

## Prerequisites

### 1. Stable Styrened Release

Before deploying to production:
- [ ] All critical bugs resolved
- [ ] Security audit completed
- [ ] Performance benchmarks validated
- [ ] Documentation complete
- [ ] Release tagged (e.g., `v1.0.0`)

### 2. Vanderlyn Repository Structure

Create these directories/files in infrastructure repo:
```
infrastructure/
├── apps/
│   ├── argocd/
│   │   └── applications/
│   │       └── styrened.yaml          # Copy from application.yaml
│   └── styrened/
│       └── values.yaml                 # Copy from values.yaml
```

### 3. ImagePullSecret

Create secret for pulling images from GHCR:

```bash
# Set kubectl context to brutus
export KUBECONFIG=~/.kube/config-brutus

# Create styrened namespace
kubectl create namespace styrened

# Create ImagePullSecret
kubectl create secret docker-registry ghcr-secret \
  --docker-server=ghcr.io \
  --docker-username=$(gh api user -q .login) \
  --docker-password=$(gh auth token) \
  -n styrened

# Verify secret
kubectl get secret ghcr-secret -n styrened
```

### 4. Production Image Available

Ensure production image exists in GHCR:
```bash
# Check available tags
gh api /orgs/styrene-lab/packages/container/styrened/versions

# Expected tags:
# - latest (from latest release)
# - v1.0.0 (specific version)
# - edge (main branch)
```

## Deployment Steps

### Step 1: Prepare Manifests

```bash
# In infrastructure repository
cd /path/to/infrastructure

# Create directory structure
mkdir -p apps/styrened
mkdir -p apps/argocd/applications

# Copy example manifests
cp /path/to/styrened/docs/examples/argocd/application.yaml \
   apps/argocd/applications/styrened.yaml

cp /path/to/styrened/docs/examples/argocd/values.yaml \
   apps/styrened/values.yaml
```

### Step 2: Customize Values

Edit `apps/styrened/values.yaml`:

```yaml
# Set specific version (not 'latest')
image:
  tag: v1.0.0  # Pin to stable version

# Adjust resource limits based on actual usage
resources:
  limits:
    cpu: 500m
    memory: 512Mi

# Configure mesh mode
styrene:
  reticulum:
    mode: standalone  # or hub, peer
    transport_enabled: true

# Enable ingress if needed
ingress:
  enabled: true
  hosts:
    - host: styrened.example.com
```

### Step 3: Commit and Push

```bash
# In infrastructure repository
git add apps/argocd/applications/styrened.yaml
git add apps/styrened/values.yaml

git commit -m "Add styrened production deployment

- ArgoCD Application with sync wave 10
- Production values with specific version pinning
- ImagePullSecret configured for GHCR access
"

git push origin main
```

### Step 4: Monitor ArgoCD Sync

ArgoCD will automatically detect and sync within ~3 minutes:

```bash
# Watch for application creation
kubectl --kubeconfig ~/.kube/config-brutus get applications -n argocd -w

# Check sync status
kubectl --kubeconfig ~/.kube/config-brutus get application styrened -n argocd

# View detailed status
kubectl --kubeconfig ~/.kube/config-brutus get application styrened -n argocd \
  -o jsonpath='{.status.sync.status}' && echo
```

### Step 5: Verify Deployment

```bash
# Check pods
kubectl --kubeconfig ~/.kube/config-brutus get pods -n styrened

# Expected output:
# NAME                 READY   STATUS    RESTARTS   AGE
# styrened-test-0      1/1     Running   0          5m
# styrened-test-1      1/1     Running   0          5m
# styrened-test-2      1/1     Running   0          5m

# Check logs
kubectl --kubeconfig ~/.kube/config-brutus logs -l app.kubernetes.io/instance=styrened-test \
  -n styrened --tail=50

# Check StatefulSet
kubectl --kubeconfig ~/.kube/config-brutus get statefulset -n styrened

# Check service
kubectl --kubeconfig ~/.kube/config-brutus get svc -n styrened
```

### Step 6: Access Application

**Via port-forward** (for testing):
```bash
kubectl --kubeconfig ~/.kube/config-brutus port-forward -n styrened svc/styrened-test 4242:4242

# Test RNS connectivity
rnsh styrened-test-0.styrened-test.styrened.svc.cluster.local:4242
```

**Via ingress** (if enabled):
```bash
# Access HTTP API
curl https://styrened.example.com/api/status

# Check ingress
kubectl --kubeconfig ~/.kube/config-brutus get ingress -n styrened
```

## Manual Sync (Optional)

If you need to force an immediate sync:

```bash
# Trigger sync via kubectl
kubectl --kubeconfig ~/.kube/config-brutus patch application styrened -n argocd \
  --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'

# Or use ArgoCD CLI
argocd app sync styrened

# Or via ArgoCD UI
# Navigate to: https://argocd.example.com/applications/styrened
# Click "Sync" button
```

## Rollback

If deployment fails or has issues:

### Option 1: Git Revert
```bash
# In infrastructure repository
git revert <commit-sha>
git push origin main

# ArgoCD will auto-sync and revert changes
```

### Option 2: Pin to Previous Version
```bash
# Edit apps/styrened/values.yaml
image:
  tag: v0.9.0  # Previous stable version

git commit -am "Rollback styrened to v0.9.0"
git push origin main
```

### Option 3: Manual Rollback via ArgoCD
```bash
# View application history
argocd app history styrened

# Rollback to specific revision
argocd app rollback styrened <revision-number>

# Or via kubectl
kubectl --kubeconfig ~/.kube/config-brutus patch application styrened -n argocd \
  --type merge -p '{"operation":{"sync":{"revision":"<commit-sha>"}}}'
```

## Updating Deployment

All updates go through git:

```bash
# In infrastructure repository
cd /path/to/infrastructure

# Edit values
vim apps/styrened/values.yaml

# Example: Update to new version
# image:
#   tag: v1.1.0

# Commit and push
git commit -am "Update styrened to v1.1.0"
git push origin main

# ArgoCD will auto-sync within 3 minutes
```

## Troubleshooting

### Sync Failing

Check ArgoCD application status:
```bash
kubectl --kubeconfig ~/.kube/config-brutus get application styrened -n argocd -o yaml
```

Common issues:
- **ImagePullBackOff**: Secret missing or expired
- **CrashLoopBackOff**: Configuration error in values.yaml
- **Sync timeout**: Large deployment or slow image pull

### Pods Not Starting

```bash
# Describe pod for events
kubectl --kubeconfig ~/.kube/config-brutus describe pod styrened-test-0 -n styrened

# Check logs
kubectl --kubeconfig ~/.kube/config-brutus logs styrened-test-0 -n styrened

# Check StatefulSet events
kubectl --kubeconfig ~/.kube/config-brutus describe statefulset styrened-test -n styrened
```

### Manual Deletion

If you need to completely remove the deployment:

```bash
# Delete ArgoCD Application (will cascade to K8s resources)
kubectl --kubeconfig ~/.kube/config-brutus delete application styrened -n argocd

# Or remove from git (ArgoCD will auto-prune)
cd /path/to/infrastructure
git rm apps/argocd/applications/styrened.yaml
git rm -r apps/styrened
git commit -m "Remove styrened deployment"
git push origin main
```

## Monitoring

### ArgoCD UI

Access at: `https://argocd.example.com`

View:
- Sync status
- Health status
- Resource tree
- Application logs
- Sync history

### kubectl Monitoring

```bash
# Application status
kubectl --kubeconfig ~/.kube/config-brutus get applications -n argocd

# Pod status
kubectl --kubeconfig ~/.kube/config-brutus get pods -n styrened -w

# Events
kubectl --kubeconfig ~/.kube/config-brutus get events -n styrened --sort-by='.lastTimestamp'

# Resource usage
kubectl --kubeconfig ~/.kube/config-brutus top pods -n styrened
```

## Comparison: ArgoCD vs Pytest

| Aspect | ArgoCD (Production) | Pytest (Testing) |
|--------|---------------------|------------------|
| **Purpose** | Long-lived production deployment | Ephemeral testing |
| **Namespace** | `styrened` (persistent) | `styrene-test-<hash>` (temporary) |
| **Image** | `ghcr.io/styrene-lab/styrened:v1.0.0` | `ghcr.io/styrene-lab/styrened-test:latest` |
| **Lifecycle** | Managed by ArgoCD, git commits | Managed by pytest, auto-cleanup |
| **Sync** | Auto-sync every 3 min | Immediate (no sync delay) |
| **Visibility** | ArgoCD UI + kubectl | kubectl + pytest output |
| **Rollback** | Git revert or ArgoCD rollback | Delete and redeploy |
| **Use Case** | Production mesh operations | Development and CI testing |

## When to Use ArgoCD

**Use ArgoCD when:**
- Deploying to production
- Need GitOps workflow
- Want declarative configuration
- Need rollback capability
- Want sync wave ordering
- Need self-healing deployments

**Don't use ArgoCD for:**
- Development iteration (too slow)
- Ephemeral testing (pytest is better)
- Rapid prototyping (manual kubectl is faster)
- CI testing (pytest handles this)

## Next Steps

When styrened is ready for production:

1. **Stabilize** - Resolve all critical issues
2. **Test** - Run full test suite (`just test-k8s-remote`)
3. **Document** - Update production deployment docs
4. **Tag** - Create release tag (`v1.0.0`)
5. **Deploy** - Follow deployment steps above
6. **Monitor** - Watch ArgoCD and pod metrics
7. **Iterate** - Update via git commits

## See Also

- [ARGOCD-INTEGRATION-ASSESSMENT.md](../../ARGOCD-INTEGRATION-ASSESSMENT.md) - Full analysis
- [REMOTE-TESTING.md](../../../tests/k8s/REMOTE-TESTING.md) - Remote cluster testing guide
- [CONTAINERS.md](../../CONTAINERS.md) - Container build pipeline
- Infrastructure ArgoCD documentation
