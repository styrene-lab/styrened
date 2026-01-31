# Docker Buildx Bake configuration for styrened
# Multi-platform builds with semantic versioning and caching

# Variables that can be overridden at build time
variable "VERSION" {
  default = "0.0.0-dev"
}

variable "COMMIT_SHA" {
  default = "unknown"
}

variable "BUILD_DATE" {
  default = ""
}

variable "REGISTRY" {
  default = "ghcr.io"
}

variable "IMAGE_NAME" {
  default = "styrene-lab/styrened-test"
}

# Build platforms
variable "PLATFORMS" {
  default = ["linux/amd64", "linux/arm64"]
}

# Cache configuration for GitHub Actions
variable "CACHE_FROM" {
  default = ""
}

variable "CACHE_TO" {
  default = ""
}

# Function to generate image tags
function "tags" {
  params = [registry, image, version, commit]
  result = [
    # Always tag with version
    "${registry}/${image}:${version}",
    # Add commit SHA tag
    "${registry}/${image}:${commit}",
  ]
}

# Generate additional tags for releases
function "release_tags" {
  params = [registry, image, version]
  result = [
    # Parse semantic version components
    # For version like "1.2.3" -> "1.2.3", "1.2", "1", "latest"
    # For version like "1.2.3-rc1" -> "1.2.3-rc1", "prerelease"
    "${registry}/${image}:${version}",
    "${registry}/${image}:latest"
  ]
}

# Base target configuration
target "default" {
  dockerfile = "Dockerfile"
  context    = "../../.."
  platforms  = PLATFORMS

  labels = {
    "org.opencontainers.image.title"       = "styrened"
    "org.opencontainers.image.description" = "Headless Styrene daemon for edge deployments"
    "org.opencontainers.image.version"     = VERSION
    "org.opencontainers.image.revision"    = COMMIT_SHA
    "org.opencontainers.image.created"     = BUILD_DATE
    "org.opencontainers.image.source"      = "https://github.com/styrene-lab/styrened"
    "org.opencontainers.image.licenses"    = "MIT"
  }

  args = {
    VERSION    = VERSION
    COMMIT_SHA = COMMIT_SHA
    BUILD_DATE = BUILD_DATE
  }

  # Cache configuration (populated by CI)
  cache-from = CACHE_FROM != "" ? [CACHE_FROM] : []
  cache-to   = CACHE_TO != "" ? [CACHE_TO] : []
}

# Local build target (single architecture, auto-detected)
target "local" {
  inherits   = ["default"]
  platforms  = []  # Auto-detect local platform
  tags       = tags(REGISTRY, IMAGE_NAME, VERSION, COMMIT_SHA)
  output     = ["type=docker"]
}

# Multi-architecture build target
target "multi" {
  inherits   = ["default"]
  platforms  = PLATFORMS
  tags       = tags(REGISTRY, IMAGE_NAME, VERSION, COMMIT_SHA)
  output     = ["type=image"]
}

# Release target (multi-arch with full tag set)
target "release" {
  inherits   = ["default"]
  platforms  = PLATFORMS
  tags       = release_tags(REGISTRY, IMAGE_NAME, VERSION)
  output     = ["type=image,push=true"]
}

# Development/edge target (main branch builds)
target "edge" {
  inherits   = ["default"]
  platforms  = PLATFORMS
  tags = [
    "${REGISTRY}/${IMAGE_NAME}:edge",
    "${REGISTRY}/${IMAGE_NAME}:main-${COMMIT_SHA}"
  ]
  output = ["type=image,push=true"]
}

# PR build target
target "pr" {
  inherits   = ["default"]
  platforms  = PLATFORMS
  tags = [
    "${REGISTRY}/${IMAGE_NAME}:pr-${COMMIT_SHA}"
  ]
  output = ["type=image"]
}

# Test target (single arch for quick validation)
target "test" {
  inherits   = ["default"]
  platforms  = ["linux/amd64"]
  tags       = ["${IMAGE_NAME}:test"]
  output     = ["type=docker"]
  target     = "test"
}

# Group for common multi-arch build
group "build-multi" {
  targets = ["multi"]
}

# Group for release builds
group "build-release" {
  targets = ["release"]
}
