# Styrened K8s Test Infrastructure Setup

This guide covers setting up the containerized test environment for styrened on Kubernetes.

## Prerequisites

### Local K8s (Recommended for Development)

**Option A: kind (Kubernetes in Docker)**

```bash
# Install kind
brew install kind

# Or via go
go install sigs.k8s.io/kind@latest

# Create cluster
kind create cluster --name styrened-test

# Verify
kubectl cluster-info --context kind-styrened-test
```

**Option B: k3d (k3s in Docker)**

```bash
# Install k3d
brew install k3d

# Create cluster
k3d cluster create styrened-test

# Verify
kubectl cluster-info
```

### Cloud K8s (For CI/CD)

The test suite auto-detects cloud clusters via `KUBECONFIG`. Supports:
- GKE (Google Kubernetes Engine)
- EKS (Amazon Elastic Kubernetes Service)
- AKS (Azure Kubernetes Service)

## Building the Container Image

### Local Build

```bash
# Build test image via Nix
just build-test

# Load into local podman
just load-test

# For kind: Load image into cluster
just load-k8s-image

# Or manually:
podman save ghcr.io/styrene-lab/styrened-test:$(cat VERSION) | \
    kind load image-archive /dev/stdin --name styrened-test
```

### Direct Nix Build

```bash
# Build test image directly
nix build .#oci-test

# Load into podman (via nix2container)
nix run .#oci-test.copyToPodman
```

## Helm Chart Usage

### Basic Deployment

```bash
cd tests/k8s/helm

# Install with defaults (3 replicas, standalone mode)
helm install styrene-test ./styrened-test

# Check status
kubectl get pods -l app.kubernetes.io/name=styrened-test

# View logs
kubectl logs -l app.kubernetes.io/name=styrened-test --tail=50
```

### Custom Configuration

```bash
# Deploy 5 pods with gateway mode
helm install styrene-test ./styrened-test \
  --set replicaCount=5 \
  --set styrene.reticulum.mode=gateway \
  --set styrene.reticulum.transport_enabled=true

# Deploy with custom RNS config
helm install styrene-test ./styrened-test \
  --values custom-values.yaml
```

### Using Different Namespaces

```bash
# Create test namespace
kubectl create namespace styrene-edge-test

# Deploy to namespace
helm install styrene-test ./styrened-test -n styrene-edge-test

# Cleanup
helm uninstall styrene-test -n styrene-edge-test
kubectl delete namespace styrene-edge-test
```

## Configuration

### ConfigMap Structure

The Helm chart creates two ConfigMaps:

**`styrened-test-config`** - Styrene configuration:
```yaml
reticulum:
  mode: standalone  # standalone, hub, peer, gateway
  transport_enabled: false
  announce_interval: 300
rpc:
  enabled: true
discovery:
  announce_interval: 300
```

**`styrened-test-rns`** - Reticulum configuration:
```
[reticulum]
enable_transport = false
share_instance = true

[interfaces]
[[TCPServerInterface]]
enabled = true
listen_ip = 0.0.0.0
listen_port = 4242
```

### Pod DNS Names

With StatefulSet, pods get stable DNS names:

```
<pod-name>.<service-name>.<namespace>.svc.cluster.local
```

Example:
- `styrene-test-0.styrene-test.default.svc.cluster.local`
- `styrene-test-1.styrene-test.default.svc.cluster.local`

Pods can connect to each other via these DNS names.

## Testing the Deployment

### Verify Pods are Running

```bash
kubectl get pods -l app.kubernetes.io/name=styrened-test

# Expected output:
# NAME              READY   STATUS    RESTARTS   AGE
# styrene-test-0    1/1     Running   0          30s
# styrene-test-1    1/1     Running   0          28s
# styrene-test-2    1/1     Running   0          26s
```

### Check RNS Initialization

```bash
# View logs from first pod
kubectl logs styrene-test-0

# Should see:
# [entrypoint] Starting styrened...
# [styrened] RNS service initialized
# [styrened] Announced as Styrene node
```

### Test Pod-to-Pod Communication

```bash
# Exec into pod 0
kubectl exec -it styrene-test-0 -- /bin/bash

# Ping pod 1 via DNS
ping styrene-test-1.styrene-test.default.svc.cluster.local

# Test RNS connectivity (if rnstatus is available)
rnstatus

# Exit
exit
```

## Resource Usage

Per pod:
- CPU: 100m request, 200m limit
- Memory: 128Mi request, 256Mi limit

For 10 pods:
- Total CPU: 1-2 cores
- Total Memory: 1.25-2.5 GB

Cost-efficient for CI/CD and local development.

## Cleanup

```bash
# Uninstall Helm release
helm uninstall styrene-test

# Or with namespace
helm uninstall styrene-test -n <namespace>
kubectl delete namespace <namespace>

# Delete kind cluster
kind delete cluster --name styrened-test

# Delete k3d cluster
k3d cluster delete styrened-test
```

## Troubleshooting

### Pods in CrashLoopBackOff

```bash
# Check pod events
kubectl describe pod styrene-test-0

# Check logs
kubectl logs styrene-test-0

# Common issues:
# - Image not found: Load image into kind/k3d
# - Config error: Check ConfigMap
# - RNS init failure: Check RNS config syntax
```

### Pods Can't Communicate

```bash
# Check NetworkPolicy
kubectl get networkpolicy

# Verify DNS
kubectl exec -it styrene-test-0 -- nslookup styrene-test-1.styrene-test.default.svc.cluster.local

# Check RNS interfaces
kubectl exec -it styrene-test-0 -- cat /root/.reticulum/config
```

### Image Pull Errors

```bash
# For local images, ensure loaded into cluster
kind load docker-image styrened-test:latest --name styrened-test

# Or set imagePullPolicy to Never
helm install styrene-test ./styrened-test --set image.pullPolicy=Never
```

## Next Steps

- **Run Test Scenarios**: See `tests/k8s/README.md` for pytest usage
- **CI Integration**: See `.github/workflows/k8s-tests.yml` example
- **Advanced Configs**: Create custom `values.yaml` for specific scenarios
