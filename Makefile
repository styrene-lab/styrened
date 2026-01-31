# Makefile for styrened development and build automation

# Variables
SHELL := /bin/bash
PROJECT_ROOT := $(shell pwd)
DOCKER_DIR := $(PROJECT_ROOT)/tests/k8s/docker
VERSION := $(shell $(PROJECT_ROOT)/scripts/version.sh version)
COMMIT_SHA := $(shell $(PROJECT_ROOT)/scripts/version.sh sha)
BUILD_DATE := $(shell date -u +"%Y-%m-%dT%H:%M:%SZ")
REGISTRY := ghcr.io
IMAGE_NAME := styrene-lab/styrened-test
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
test: ## Run all tests
	pytest tests/

.PHONY: test-unit
test-unit: ## Run unit tests only
	pytest tests/ -k "not k8s"

.PHONY: test-k8s
test-k8s: ## Run k8s integration tests
	pytest tests/k8s/

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

##@ Docker Build

.PHONY: version
version: ## Display version information
	@echo "$(INFO_COLOR)Version Information:$(NO_COLOR)"
	@echo "  Version:    $(VERSION)"
	@echo "  Commit:     $(COMMIT_SHA)"
	@echo "  Build Date: $(BUILD_DATE)"
	@echo "  Image:      $(IMAGE_TAG)"

.PHONY: build
build: ## Build local Docker image (auto-detect architecture)
	@echo "$(INFO_COLOR)Building local image...$(NO_COLOR)"
	cd $(DOCKER_DIR) && docker buildx bake \
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
push: build-multi ## Build and push multi-arch image to registry
	@echo "$(INFO_COLOR)Pushing image to registry...$(NO_COLOR)"
	cd $(DOCKER_DIR) && docker buildx bake \
		--set "*.context=$(PROJECT_ROOT)" \
		--set "*.args.VERSION=$(VERSION)" \
		--set "*.args.COMMIT_SHA=$(COMMIT_SHA)" \
		--set "*.args.BUILD_DATE=$(BUILD_DATE)" \
		--set "multi.tags=$(IMAGE_TAG)" \
		--set "multi.tags=$(REGISTRY)/$(IMAGE_NAME):$(COMMIT_SHA)" \
		--set "multi.output=type=image,push=true" \
		multi
	@echo "$(SUCCESS_COLOR)Pushed: $(IMAGE_TAG)$(NO_COLOR)"

.PHONY: test-image
test-image: ## Quick validation of built image
	@echo "$(INFO_COLOR)Testing image...$(NO_COLOR)"
	@docker run --rm $(IMAGE_TAG) styrened --version 2>/dev/null && \
		echo "$(SUCCESS_COLOR)Image validation passed$(NO_COLOR)" || \
		echo "$(WARN_COLOR)Image validation failed$(NO_COLOR)"

.PHONY: clean-images
clean-images: ## Remove local Docker images
	@echo "$(INFO_COLOR)Removing local images...$(NO_COLOR)"
	docker rmi $(IMAGE_TAG) 2>/dev/null || true
	docker rmi $(REGISTRY)/$(IMAGE_NAME):$(COMMIT_SHA) 2>/dev/null || true
	docker rmi $(IMAGE_NAME):test 2>/dev/null || true
	@echo "$(SUCCESS_COLOR)Cleaned local images$(NO_COLOR)"

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
