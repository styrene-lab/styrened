# Multi-stage Dockerfile for styrened k8s testing
# Optimized for fast iteration with layer caching

# Stage 1: Base with system dependencies
FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    iputils-ping \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Stage 2: Dependencies layer (cached unless pyproject.toml changes)
FROM base AS deps

WORKDIR /app

# Copy only dependency specification first for better caching
COPY pyproject.toml README.md ./

# Install dependencies without the package itself
RUN pip install --no-cache-dir \
    rns>=0.7.5 \
    lxmf>=0.4.3 \
    pyyaml>=6.0 \
    platformdirs>=4.0 \
    sqlalchemy>=2.0 \
    msgpack>=1.0

# Stage 3: Application layer
FROM deps AS app

WORKDIR /app

# Copy source code
COPY src/ ./src/

# Install styrened in editable mode
RUN pip install --no-cache-dir -e .

# Stage 4: Test layer
FROM app AS test

# Install test dependencies
RUN pip install --no-cache-dir pytest pytest-asyncio

# Copy entrypoint
COPY tests/k8s/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create directories for RNS and styrene data
RUN mkdir -p /root/.styrene /root/.reticulum /config /data

# Build args for version info
ARG VERSION=0.0.0-dev
ARG COMMIT_SHA=unknown
ARG BUILD_DATE=unknown

# Labels
LABEL org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${COMMIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}"

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    RNS_LOGLEVEL=4 \
    STYRENE_CONFIG_DIR=/config \
    STYRENE_VERSION=${VERSION}

# Entrypoint
ENTRYPOINT ["/entrypoint.sh"]
CMD ["styrened"]
