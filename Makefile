# Makefile for styrened development and build automation

# Variables
SHELL := /bin/bash
PROJECT_ROOT := $(shell pwd)
DOCKER_DIR := $(PROJECT_ROOT)/tests/k8s/docker
VERSION := $(shell $(PROJECT_ROOT)/scripts/version.sh version)
COMMIT_SHA := $(shell $(PROJECT_ROOT)/scripts/version.sh sha)
BUILD_DATE := $(shell date -u +"%Y-%m-%dT%H:%M:%SZ")
REGISTRY := ghcr.io
IMAGE_NAME_PROD := styrene-lab/styrened
IMAGE_NAME_TEST := styrene-lab/styrened-test
IMAGE_NAME := $(IMAGE_NAME_TEST)
IMAGE_TAG := $(REGISTRY)/$(IMAGE_NAME):$(VERSION)

# Colors for output
NO_COLOR := \033[0m
INFO_COLOR := \033[0;36m
SUCCESS_COLOR := \033[0;32m
WARN_COLOR := \033[0;33m

.PHONY: help
help: ## Show this help message
	@echo "$(INFO_COLOR)Available targets:$(NO_COLOR)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(SUCCESS_COLOR)%-20s$(NO_COLOR) %s\n", $$1, $$2}'

##@ Development

.PHONY: install
install: ## Install package with dev dependencies
	pip install -e ".[dev]"

.PHONY: test
test: ## Run all tests (unit + integration, no k8s)
	pytest tests/ --ignore=tests/k8s/

.PHONY: test-unit
test-unit: ## Run unit tests only
	pytest tests/test_*.py -v

.PHONY: test-integration
test-integration: ## Run local integration tests (no k8s)
	pytest tests/integration/ -v

.PHONY: test-k8s
test-k8s: ## Run k8s integration tests (requires cluster)
	pytest tests/k8s/

.PHONY: test-k8s-smoke
test-k8s-smoke: ## Run k8s smoke tests only (fast)
	pytest tests/k8s/scenarios/ -m smoke -v

.PHONY: test-k8s-full
test-k8s-full: ## Run full k8s test suite including slow tests
	pytest tests/k8s/scenarios/ --run-slow -v

.PHONY: lint
lint: ## Run linter (ruff)
	ruff check src/ tests/

.PHONY: format
format: ## Format code (ruff)
	ruff format src/ tests/

.PHONY: typecheck
typecheck: ## Run type checker (mypy)
	mypy src/

.PHONY: validate
validate: lint typecheck test ## Run all validation checks

##@ Documentation

.PHONY: docs
docs: ## Generate API documentation (output: docs/api/)
	@echo "$(INFO_COLOR)Generating API documentation...$(NO_COLOR)"
	@pip show pdoc >/dev/null 2>&1 || { echo "$(WARN_COLOR)pdoc not installed. Run: pip install -e '.[docs]'$(NO_COLOR)"; exit 1; }
	pdoc src/styrened -o docs/api --docformat google
	@echo "$(SUCCESS_COLOR)Generated: docs/api/$(NO_COLOR)"

.PHONY: docs-serve
docs-serve: ## Serve API documentation locally (live reload)
	@echo "$(INFO_COLOR)Starting documentation server...$(NO_COLOR)"
	@pip show pdoc >/dev/null 2>&1 || { echo "$(WARN_COLOR)pdoc not installed. Run: pip install -e '.[docs]'$(NO_COLOR)"; exit 1; }
	pdoc src/styrened --docformat google

.PHONY: docs-clean
docs-clean: ## Remove generated documentation
	rm -rf docs/api/
	@echo "$(SUCCESS_COLOR)Cleaned: docs/api/$(NO_COLOR)"

##@ Container Build
#
# Image naming:
#   - Test images:       ghcr.io/styrene-lab/styrened-test
#   - Production images: ghcr.io/styrene-lab/styrened
#
# Tagging strategy:
#   - Development:  <version>, <commit-sha>
#   - Nightly:      latest (test), edge (prod), <commit-sha>
#   - Release:      <version>, <commit-sha>, latest (stable only)
#
# Common workflows:
#   Local build:      make build-prod
#   Push to GHCR:     make push-prod (requires GITHUB_TOKEN)
#   Nightly build:    make push-test-nightly && make push-edge
#   Release build:    make push-prod-latest

.PHONY: version
version: ## Display version information
	@echo "$(INFO_COLOR)Version Information:$(NO_COLOR)"
	@echo "  Version:    $(VERSION)"
	@echo "  Commit:     $(COMMIT_SHA)"
	@echo "  Build Date: $(BUILD_DATE)"
	@echo "  Image:      $(IMAGE_TAG)"

.PHONY: build
build: ## Build local container image (auto-detect architecture)
	@echo "$(INFO_COLOR)Building local image...$(NO_COLOR)"
	cd $(DOCKER_DIR) && docker buildx bake \
		--allow=fs.read=$(PROJECT_ROOT) \
		--set "*.context=$(PROJECT_ROOT)" \
		--set "*.args.VERSION=$(VERSION)" \
		--set "*.args.COMMIT_SHA=$(COMMIT_SHA)" \
		--set "*.args.BUILD_DATE=$(BUILD_DATE)" \
		--set "local.tags=$(IMAGE_TAG)" \
		--set "local.tags=$(REGISTRY)/$(IMAGE_NAME):$(COMMIT_SHA)" \
		--load \
		local
	@echo "$(SUCCESS_COLOR)Built: $(IMAGE_TAG)$(NO_COLOR)"

.PHONY: build-multi
build-multi: ## Build multi-architecture image (AMD64, ARM64)
	@echo "$(INFO_COLOR)Building multi-architecture image...$(NO_COLOR)"
	cd $(DOCKER_DIR) && docker buildx bake \
		--set "*.context=$(PROJECT_ROOT)" \
		--set "*.args.VERSION=$(VERSION)" \
		--set "*.args.COMMIT_SHA=$(COMMIT_SHA)" \
		--set "*.args.BUILD_DATE=$(BUILD_DATE)" \
		--set "multi.tags=$(IMAGE_TAG)" \
		--set "multi.tags=$(REGISTRY)/$(IMAGE_NAME):$(COMMIT_SHA)" \
		multi
	@echo "$(SUCCESS_COLOR)Built multi-arch: $(IMAGE_TAG)$(NO_COLOR)"

.PHONY: build-test
build-test: ## Build test stage only (quick validation)
	@echo "$(INFO_COLOR)Building test image...$(NO_COLOR)"
	cd $(DOCKER_DIR) && docker buildx bake \
		--set "*.context=$(PROJECT_ROOT)" \
		--set "*.args.VERSION=$(VERSION)" \
		--set "*.args.COMMIT_SHA=$(COMMIT_SHA)" \
		--set "*.args.BUILD_DATE=$(BUILD_DATE)" \
		--load \
		test
	@echo "$(SUCCESS_COLOR)Built test image$(NO_COLOR)"

.PHONY: push
push: push-test ## Alias for push-test (default test image push)

.PHONY: test-image
test-image: ## Quick validation of built test image
	@echo "$(INFO_COLOR)Testing image...$(NO_COLOR)"
	@docker run --rm $(IMAGE_TAG) styrened --version 2>/dev/null && \
		echo "$(SUCCESS_COLOR)Image validation passed$(NO_COLOR)" || \
		echo "$(WARN_COLOR)Image validation failed$(NO_COLOR)"

.PHONY: test-image-prod
test-image-prod: ## Quick validation of built production image
	@echo "$(INFO_COLOR)Testing production image...$(NO_COLOR)"
	@docker run --rm $(REGISTRY)/$(IMAGE_NAME_PROD):$(VERSION) styrened --version 2>/dev/null && \
		echo "$(SUCCESS_COLOR)Production image validation passed$(NO_COLOR)" || \
		echo "$(WARN_COLOR)Production image validation failed$(NO_COLOR)"

.PHONY: clean-images
clean-images: ## Remove local container images
	@echo "$(INFO_COLOR)Removing local images...$(NO_COLOR)"
	docker rmi $(IMAGE_TAG) 2>/dev/null || true
	docker rmi $(REGISTRY)/$(IMAGE_NAME):$(COMMIT_SHA) 2>/dev/null || true
	docker rmi $(REGISTRY)/$(IMAGE_NAME_PROD):$(VERSION) 2>/dev/null || true
	docker rmi $(REGISTRY)/$(IMAGE_NAME_PROD):$(COMMIT_SHA) 2>/dev/null || true
	docker rmi $(IMAGE_NAME):test 2>/dev/null || true
	@echo "$(SUCCESS_COLOR)Cleaned local images$(NO_COLOR)"

##@ Production Images

.PHONY: container-login
container-login: ## Login to GHCR (requires GITHUB_TOKEN env var)
	@echo "$(INFO_COLOR)Logging in to $(REGISTRY)...$(NO_COLOR)"
	@if [ -z "$(GITHUB_TOKEN)" ]; then \
		echo "$(WARN_COLOR)GITHUB_TOKEN not set, attempting login with stored credentials$(NO_COLOR)"; \
		echo "" | docker login $(REGISTRY) 2>/dev/null || true; \
	else \
		echo "$(GITHUB_TOKEN)" | docker login $(REGISTRY) -u $(GITHUB_ACTOR) --password-stdin; \
	fi

# Backward compatibility alias
.PHONY: docker-login
docker-login: container-login

.PHONY: build-prod
build-prod: ## Build production image (auto-detect architecture)
	@echo "$(INFO_COLOR)Building production image...$(NO_COLOR)"
	cd $(DOCKER_DIR) && docker buildx bake \
		--allow=fs.read=$(PROJECT_ROOT) \
		--set "*.context=$(PROJECT_ROOT)" \
		--set "*.args.VERSION=$(VERSION)" \
		--set "*.args.COMMIT_SHA=$(COMMIT_SHA)" \
		--set "*.args.BUILD_DATE=$(BUILD_DATE)" \
		--set "*.target=app" \
		--set "local.tags=$(REGISTRY)/$(IMAGE_NAME_PROD):$(VERSION)" \
		--set "local.tags=$(REGISTRY)/$(IMAGE_NAME_PROD):$(COMMIT_SHA)" \
		--load \
		local
	@echo "$(SUCCESS_COLOR)Built: $(REGISTRY)/$(IMAGE_NAME_PROD):$(VERSION)$(NO_COLOR)"

.PHONY: build-prod-multi
build-prod-multi: ## Build multi-arch production image (AMD64, ARM64)
	@echo "$(INFO_COLOR)Building multi-arch production image...$(NO_COLOR)"
	cd $(DOCKER_DIR) && docker buildx bake \
		--allow=fs.read=$(PROJECT_ROOT) \
		--set "*.context=$(PROJECT_ROOT)" \
		--set "*.args.VERSION=$(VERSION)" \
		--set "*.args.COMMIT_SHA=$(COMMIT_SHA)" \
		--set "*.args.BUILD_DATE=$(BUILD_DATE)" \
		--set "*.target=app" \
		--set "multi.tags=$(REGISTRY)/$(IMAGE_NAME_PROD):$(VERSION)" \
		--set "multi.tags=$(REGISTRY)/$(IMAGE_NAME_PROD):$(COMMIT_SHA)" \
		multi
	@echo "$(SUCCESS_COLOR)Built multi-arch: $(REGISTRY)/$(IMAGE_NAME_PROD):$(VERSION)$(NO_COLOR)"

.PHONY: push-prod
push-prod: container-login build-prod-multi ## Build and push production image to GHCR
	@echo "$(INFO_COLOR)Pushing production image...$(NO_COLOR)"
	cd $(DOCKER_DIR) && docker buildx bake \
		--allow=fs.read=$(PROJECT_ROOT) \
		--set "*.context=$(PROJECT_ROOT)" \
		--set "*.args.VERSION=$(VERSION)" \
		--set "*.args.COMMIT_SHA=$(COMMIT_SHA)" \
		--set "*.args.BUILD_DATE=$(BUILD_DATE)" \
		--set "*.target=app" \
		--set "multi.tags=$(REGISTRY)/$(IMAGE_NAME_PROD):$(VERSION)" \
		--set "multi.tags=$(REGISTRY)/$(IMAGE_NAME_PROD):$(COMMIT_SHA)" \
		--set "multi.output=type=image,push=true" \
		multi
	@echo "$(SUCCESS_COLOR)Pushed: $(REGISTRY)/$(IMAGE_NAME_PROD):$(VERSION)$(NO_COLOR)"

.PHONY: push-prod-latest
push-prod-latest: container-login ## Build and push with 'latest' tag (releases only)
	@echo "$(INFO_COLOR)Pushing production image with 'latest' tag...$(NO_COLOR)"
	cd $(DOCKER_DIR) && docker buildx bake \
		--allow=fs.read=$(PROJECT_ROOT) \
		--set "*.context=$(PROJECT_ROOT)" \
		--set "*.args.VERSION=$(VERSION)" \
		--set "*.args.COMMIT_SHA=$(COMMIT_SHA)" \
		--set "*.args.BUILD_DATE=$(BUILD_DATE)" \
		--set "*.target=app" \
		--set "multi.tags=$(REGISTRY)/$(IMAGE_NAME_PROD):$(VERSION)" \
		--set "multi.tags=$(REGISTRY)/$(IMAGE_NAME_PROD):$(COMMIT_SHA)" \
		--set "multi.tags=$(REGISTRY)/$(IMAGE_NAME_PROD):latest" \
		--set "multi.output=type=image,push=true" \
		multi
	@echo "$(SUCCESS_COLOR)Pushed: $(REGISTRY)/$(IMAGE_NAME_PROD):latest$(NO_COLOR)"

.PHONY: push-edge
push-edge: container-login ## Build and push edge build (main/develop branches)
	@echo "$(INFO_COLOR)Pushing edge build...$(NO_COLOR)"
	cd $(DOCKER_DIR) && docker buildx bake \
		--allow=fs.read=$(PROJECT_ROOT) \
		--set "*.context=$(PROJECT_ROOT)" \
		--set "*.args.VERSION=$(VERSION)" \
		--set "*.args.COMMIT_SHA=$(COMMIT_SHA)" \
		--set "*.args.BUILD_DATE=$(BUILD_DATE)" \
		--set "*.target=app" \
		--set "multi.tags=$(REGISTRY)/$(IMAGE_NAME_PROD):edge" \
		--set "multi.tags=$(REGISTRY)/$(IMAGE_NAME_PROD):$(COMMIT_SHA)" \
		--set "multi.output=type=image,push=true" \
		multi
	@echo "$(SUCCESS_COLOR)Pushed: $(REGISTRY)/$(IMAGE_NAME_PROD):edge$(NO_COLOR)"

.PHONY: push-test
push-test: container-login build-multi ## Build and push test image to GHCR
	@echo "$(INFO_COLOR)Pushing test image...$(NO_COLOR)"
	cd $(DOCKER_DIR) && docker buildx bake \
		--allow=fs.read=$(PROJECT_ROOT) \
		--set "*.context=$(PROJECT_ROOT)" \
		--set "*.args.VERSION=$(VERSION)" \
		--set "*.args.COMMIT_SHA=$(COMMIT_SHA)" \
		--set "*.args.BUILD_DATE=$(BUILD_DATE)" \
		--set "multi.tags=$(REGISTRY)/$(IMAGE_NAME_TEST):$(VERSION)" \
		--set "multi.tags=$(REGISTRY)/$(IMAGE_NAME_TEST):$(COMMIT_SHA)" \
		--set "multi.output=type=image,push=true" \
		multi
	@echo "$(SUCCESS_COLOR)Pushed: $(REGISTRY)/$(IMAGE_NAME_TEST):$(VERSION)$(NO_COLOR)"

.PHONY: push-test-nightly
push-test-nightly: container-login ## Build and push test image with nightly tags
	@echo "$(INFO_COLOR)Pushing nightly test image...$(NO_COLOR)"
	cd $(DOCKER_DIR) && docker buildx bake \
		--allow=fs.read=$(PROJECT_ROOT) \
		--set "*.context=$(PROJECT_ROOT)" \
		--set "*.args.VERSION=$(VERSION)" \
		--set "*.args.COMMIT_SHA=$(COMMIT_SHA)" \
		--set "*.args.BUILD_DATE=$(BUILD_DATE)" \
		--set "multi.tags=$(REGISTRY)/$(IMAGE_NAME_TEST):latest" \
		--set "multi.tags=$(REGISTRY)/$(IMAGE_NAME_TEST):$(COMMIT_SHA)" \
		--set "multi.output=type=image,push=true" \
		multi
	@echo "$(SUCCESS_COLOR)Pushed: $(REGISTRY)/$(IMAGE_NAME_TEST):latest$(NO_COLOR)"

##@ Helm / K8s Testing

HELM_CHART := $(PROJECT_ROOT)/tests/k8s/helm/styrened-test
HELM_RELEASE := styrene-test
HELM_NAMESPACE := styrene-test
# Local image tag for k8s testing (independent of registry)
LOCAL_IMAGE_TAG := styrened-test:local-amd64

.PHONY: create-ghcr-secret
create-ghcr-secret: ## Create ImagePullSecret for GHCR in test namespace
	@echo "$(INFO_COLOR)Creating GHCR ImagePullSecret...$(NO_COLOR)"
	@if [ -z "$(GITHUB_TOKEN)" ]; then \
		echo "$(WARN_COLOR)GITHUB_TOKEN not set, attempting to use gh CLI token$(NO_COLOR)"; \
		export GITHUB_TOKEN=$$(gh auth token 2>/dev/null); \
		if [ -z "$$GITHUB_TOKEN" ]; then \
			echo "$(WARN_COLOR)Failed to get token from gh CLI$(NO_COLOR)"; \
			echo "$(WARN_COLOR)Please set GITHUB_TOKEN or run 'gh auth login'$(NO_COLOR)"; \
			exit 1; \
		fi; \
	fi; \
	kubectl create namespace $(HELM_NAMESPACE) 2>/dev/null || true; \
	kubectl delete secret ghcr-secret -n $(HELM_NAMESPACE) 2>/dev/null || true; \
	kubectl create secret docker-registry ghcr-secret \
		--docker-server=ghcr.io \
		--docker-username=$${GITHUB_ACTOR:-$$(gh api user -q .login 2>/dev/null || echo "unknown")} \
		--docker-password=$${GITHUB_TOKEN:-$$(gh auth token)} \
		--docker-email=$${GITHUB_EMAIL:-noreply@github.com} \
		-n $(HELM_NAMESPACE)
	@echo "$(SUCCESS_COLOR)Created ImagePullSecret: ghcr-secret in namespace $(HELM_NAMESPACE)$(NO_COLOR)"

.PHONY: delete-ghcr-secret
delete-ghcr-secret: ## Delete GHCR ImagePullSecret from test namespace
	@echo "$(INFO_COLOR)Deleting GHCR ImagePullSecret...$(NO_COLOR)"
	kubectl delete secret ghcr-secret -n $(HELM_NAMESPACE) 2>/dev/null || true
	@echo "$(SUCCESS_COLOR)Deleted ImagePullSecret$(NO_COLOR)"

.PHONY: verify-ghcr-secret
verify-ghcr-secret: ## Verify GHCR ImagePullSecret exists and is valid
	@echo "$(INFO_COLOR)Verifying GHCR ImagePullSecret...$(NO_COLOR)"
	@kubectl get secret ghcr-secret -n $(HELM_NAMESPACE) >/dev/null 2>&1 && \
		echo "$(SUCCESS_COLOR)Secret exists$(NO_COLOR)" || \
		{ echo "$(WARN_COLOR)Secret not found. Run 'make create-ghcr-secret'$(NO_COLOR)"; exit 1; }
	@echo "$(INFO_COLOR)Secret details:$(NO_COLOR)"
	@kubectl get secret ghcr-secret -n $(HELM_NAMESPACE) -o yaml | grep "^\s*\.dockerconfigjson:" | wc -c | \
		awk '{if ($$1 > 50) print "  Size: " $$1 " bytes (looks valid)"; else print "  Size: " $$1 " bytes (may be invalid)"}'

.PHONY: build-amd64
build-amd64: ## Build AMD64 image for x86_64 clusters (from any host)
	@echo "$(INFO_COLOR)Building AMD64 image...$(NO_COLOR)"
	docker buildx build \
		--platform linux/amd64 \
		-t $(LOCAL_IMAGE_TAG) \
		-f $(DOCKER_DIR)/Dockerfile \
		--load \
		$(PROJECT_ROOT)
	@echo "$(SUCCESS_COLOR)Built: $(LOCAL_IMAGE_TAG)$(NO_COLOR)"

.PHONY: load-k8s-image
load-k8s-image: ## Load local image into k8s cluster (auto-detect kind/k3d/k3s)
	@echo "$(INFO_COLOR)Loading image into k8s cluster...$(NO_COLOR)"
	@if kubectl config current-context 2>/dev/null | grep -q "kind-"; then \
		echo "  Detected: kind cluster"; \
		kind load docker-image $(LOCAL_IMAGE_TAG) --name $$(kubectl config current-context | sed 's/kind-//'); \
	elif kubectl config current-context 2>/dev/null | grep -q "k3d-"; then \
		echo "  Detected: k3d cluster"; \
		k3d image import $(LOCAL_IMAGE_TAG) -c $$(kubectl config current-context | sed 's/k3d-//'); \
	elif command -v k3s >/dev/null 2>&1 || ssh $${K3S_HOST:-brutus} "command -v k3s" >/dev/null 2>&1; then \
		echo "  Detected: k3s cluster (remote)"; \
		docker save $(LOCAL_IMAGE_TAG) | gzip > /tmp/$(LOCAL_IMAGE_TAG).tar.gz; \
		scp /tmp/$(LOCAL_IMAGE_TAG).tar.gz $${K3S_HOST:-brutus}:/tmp/; \
		ssh $${K3S_HOST:-brutus} "sudo k3s ctr images import /tmp/$(LOCAL_IMAGE_TAG).tar.gz"; \
		rm -f /tmp/$(LOCAL_IMAGE_TAG).tar.gz; \
	else \
		echo "$(WARN_COLOR)Unknown cluster type - please load image manually$(NO_COLOR)"; \
		exit 1; \
	fi
	@echo "$(SUCCESS_COLOR)Image loaded into cluster$(NO_COLOR)"

.PHONY: test-k8s-deploy
test-k8s-deploy: build-amd64 load-k8s-image ## Build, load image, and deploy test stack
	@echo "$(INFO_COLOR)Deploying test stack...$(NO_COLOR)"
	helm upgrade --install $(HELM_RELEASE) $(HELM_CHART) \
		-n $(HELM_NAMESPACE) --create-namespace \
		--set image.repository=styrened-test \
		--set image.tag=local-amd64 \
		--set image.pullPolicy=Never
	@echo "$(SUCCESS_COLOR)Deployed: $(HELM_RELEASE)$(NO_COLOR)"
	@echo "$(INFO_COLOR)Waiting for pods to be ready...$(NO_COLOR)"
	kubectl wait --for=condition=ready pod -l app.kubernetes.io/instance=$(HELM_RELEASE) \
		-n $(HELM_NAMESPACE) --timeout=120s || true
	kubectl get pods -n $(HELM_NAMESPACE)

.PHONY: test-k8s-run
test-k8s-run: ## Run k8s tests (assumes image already deployed)
	@echo "$(INFO_COLOR)Running k8s integration tests...$(NO_COLOR)"
	pytest tests/k8s/scenarios/ -v -m smoke --tb=short

.PHONY: test-k8s-local
test-k8s-local: build-amd64 load-k8s-image ## Build image, load to cluster, run smoke tests
	@echo "$(INFO_COLOR)=== K8s Integration Test Workflow ===$(NO_COLOR)"
	@echo "$(INFO_COLOR)Running smoke tests...$(NO_COLOR)"
	pytest tests/k8s/scenarios/ -v -m smoke --tb=short
	@echo "$(SUCCESS_COLOR)=== Test workflow complete ===$(NO_COLOR)"

.PHONY: test-k8s-remote
test-k8s-remote: create-ghcr-secret helm-install-ghcr ## Setup secret, deploy from GHCR, run smoke tests
	@echo "$(INFO_COLOR)=== K8s Remote Test Workflow (GHCR) ===$(NO_COLOR)"
	@echo "$(INFO_COLOR)Running smoke tests...$(NO_COLOR)"
	pytest tests/k8s/scenarios/ -v -m smoke --tb=short
	@echo "$(SUCCESS_COLOR)=== Remote test workflow complete ===$(NO_COLOR)"

.PHONY: helm-template
helm-template: ## Render Helm templates (dry-run)
	@echo "$(INFO_COLOR)Rendering Helm templates...$(NO_COLOR)"
	helm template $(HELM_RELEASE) $(HELM_CHART) -n $(HELM_NAMESPACE)

.PHONY: helm-install
helm-install: ## Deploy test stack to k8s cluster (local images)
	@echo "$(INFO_COLOR)Deploying to k8s...$(NO_COLOR)"
	helm upgrade --install $(HELM_RELEASE) $(HELM_CHART) \
		-n $(HELM_NAMESPACE) --create-namespace \
		--set image.repository=styrened-test \
		--set image.tag=local-amd64 \
		--set image.pullPolicy=Never
	@echo "$(SUCCESS_COLOR)Deployed: $(HELM_RELEASE) to $(HELM_NAMESPACE)$(NO_COLOR)"

.PHONY: helm-install-ghcr
helm-install-ghcr: verify-ghcr-secret ## Deploy test stack using GHCR images
	@echo "$(INFO_COLOR)Deploying from GHCR...$(NO_COLOR)"
	helm upgrade --install $(HELM_RELEASE) $(HELM_CHART) \
		-n $(HELM_NAMESPACE) --create-namespace \
		--set image.repository=$(REGISTRY)/$(IMAGE_NAME_TEST) \
		--set image.tag=$(VERSION) \
		--set image.pullPolicy=Always \
		--set imagePullSecrets[0].name=ghcr-secret
	@echo "$(SUCCESS_COLOR)Deployed: $(HELM_RELEASE) from GHCR$(NO_COLOR)"
	@echo "$(INFO_COLOR)Waiting for pods to be ready...$(NO_COLOR)"
	kubectl wait --for=condition=ready pod -l app.kubernetes.io/instance=$(HELM_RELEASE) \
		-n $(HELM_NAMESPACE) --timeout=120s || true
	kubectl get pods -n $(HELM_NAMESPACE)

.PHONY: helm-install-local
helm-install-local: build helm-install ## Build image and deploy to local k8s
	@echo "$(SUCCESS_COLOR)Local deployment complete$(NO_COLOR)"

.PHONY: helm-uninstall
helm-uninstall: ## Remove test stack from k8s cluster
	@echo "$(INFO_COLOR)Removing from k8s...$(NO_COLOR)"
	helm uninstall $(HELM_RELEASE) -n $(HELM_NAMESPACE) || true
	kubectl delete namespace $(HELM_NAMESPACE) --wait=false || true
	@echo "$(SUCCESS_COLOR)Removed: $(HELM_RELEASE)$(NO_COLOR)"

.PHONY: helm-status
helm-status: ## Show deployment status
	@echo "$(INFO_COLOR)Helm release status:$(NO_COLOR)"
	helm status $(HELM_RELEASE) -n $(HELM_NAMESPACE) 2>/dev/null || echo "  Not deployed"
	@echo ""
	@echo "$(INFO_COLOR)Pod status:$(NO_COLOR)"
	kubectl get pods -n $(HELM_NAMESPACE) 2>/dev/null || echo "  No pods"

.PHONY: helm-logs
helm-logs: ## Show logs from test pods
	kubectl logs -l app.kubernetes.io/instance=$(HELM_RELEASE) -n $(HELM_NAMESPACE) --tail=50

##@ Cleanup

.PHONY: clean
clean: ## Remove cache directories
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf .mypy_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "$(SUCCESS_COLOR)Cleaned cache directories$(NO_COLOR)"

.PHONY: clean-all
clean-all: clean clean-images ## Remove all build artifacts and images
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	@echo "$(SUCCESS_COLOR)Cleaned all artifacts$(NO_COLOR)"
