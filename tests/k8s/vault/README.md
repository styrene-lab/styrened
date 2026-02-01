# Vault Secrets Operator Integration

This directory contains the VSO (Vault Secrets Operator) configuration for managing
GHCR ImagePullSecrets used by styrened K8s tests.

## Architecture

```
Vault (secret/bootstrap/ghcr/styrene-lab)
    │
    ▼ VaultStaticSecret syncs every 1h
styrene-infra namespace (ghcr-secret)
    │
    ▼ Test harness copies to test namespace
styrene-test-* namespace (ghcr-secret)
    │
    ▼ Pod uses for image pull
ghcr.io/styrene-lab/styrened-test
```

## Prerequisites

1. **Vault** running with KV-v2 secrets engine at `secret/`
2. **Vault Secrets Operator** installed in cluster
3. **Kubernetes auth** configured in Vault

## Vault Setup

The following Vault resources must exist (one-time setup):

### 1. Store GHCR credentials in Vault

```bash
# Get a GitHub token with read:packages scope
GH_TOKEN=$(gh auth token)

# Store in Vault
kubectl exec -n vault vault-0 -- vault kv put secret/bootstrap/ghcr/styrene-lab \
  username=<github-username> \
  password="$GH_TOKEN" \
  server=ghcr.io
```

### 2. Create Vault policy

```bash
kubectl exec -n vault vault-0 -- sh -c 'cat > /tmp/policy.hcl << "POLICY"
path "secret/data/bootstrap/ghcr/styrene-lab" {
  capabilities = ["read"]
}
path "secret/metadata/bootstrap/ghcr/styrene-lab" {
  capabilities = ["read"]
}
POLICY
vault policy write styrene-tests /tmp/policy.hcl'
```

### 3. Create Kubernetes auth role

```bash
kubectl exec -n vault vault-0 -- vault write auth/kubernetes/role/styrene-tests \
  bound_service_account_names="default,styrene-test" \
  bound_service_account_namespaces="styrene-*,default" \
  policies="styrene-tests" \
  ttl="1h"
```

## Kubernetes Setup

Apply the VSO resources:

```bash
# Using kustomize
kubectl apply -k tests/k8s/vault/

# Or individual files
kubectl apply -f tests/k8s/vault/namespace.yaml
kubectl apply -f tests/k8s/vault/vault-auth.yaml
kubectl apply -f tests/k8s/vault/ghcr-secret.yaml
```

## Verification

Check that the secret is synced:

```bash
# Check VaultStaticSecret status
kubectl get vaultstaticsecret -n styrene-infra

# Check the created secret
kubectl get secret ghcr-secret -n styrene-infra

# Verify dockerconfigjson format
kubectl get secret ghcr-secret -n styrene-infra -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | jq .
```

## How Tests Use This

The test harness (`harness.py`) automatically:

1. Checks if `ghcr-secret` exists in the test namespace
2. If not, copies it from `styrene-infra` namespace
3. Helm chart references `imagePullSecrets[0].name=ghcr-secret`

No manual secret creation is needed for tests once VSO is configured.

## Troubleshooting

### Secret not syncing

```bash
# Check VSO logs
kubectl logs -n vault-secrets-operator-system -l app.kubernetes.io/name=vault-secrets-operator

# Check VaultAuth status
kubectl describe vaultauth -n styrene-infra styrene-vault-auth

# Check VaultStaticSecret status
kubectl describe vaultstaticsecret -n styrene-infra ghcr-credentials
```

### Permission denied

Verify the Vault policy and K8s auth role:

```bash
kubectl exec -n vault vault-0 -- vault policy read styrene-tests
kubectl exec -n vault vault-0 -- vault read auth/kubernetes/role/styrene-tests
```

### Token expired

The GitHub token stored in Vault may expire. Refresh it:

```bash
GH_TOKEN=$(gh auth token)
kubectl exec -n vault vault-0 -- vault kv put secret/bootstrap/ghcr/styrene-lab \
  username=<github-username> \
  password="$GH_TOKEN" \
  server=ghcr.io
```

The VaultStaticSecret will automatically sync the new value within 1 hour
(or trigger a manual sync by deleting the secret).
