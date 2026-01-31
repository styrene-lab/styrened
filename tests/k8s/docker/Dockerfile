# Multi-stage Dockerfile for styrened k8s testing
# Optimized for fast iteration with layer caching

# Stage 1: Base dependencies
FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    iputils-ping \
    procps \
    iptables \
    && rm -rf /var/lib/apt/lists/*

# Install build tool
RUN pip install --no-cache-dir build

# Stage 2: Install styrene-core first
FROM base AS core

WORKDIR /app/styrene-core

# Copy styrene-core package
COPY styrene-core/pyproject.toml styrene-core/README.md ./
COPY styrene-core/src/ ./src/

# Install styrene-core
RUN pip install --no-cache-dir -e .

# Stage 3: Application layer
FROM core AS app

WORKDIR /app/styrened

# Copy styrened source code
COPY styrened/pyproject.toml styrened/README.md ./
COPY styrened/src/ ./src/

# Now install styrened (which depends on styrene-core)
RUN pip install --no-cache-dir -e .

# Stage 4: Test layer
FROM app AS test

# Install test dependencies
RUN pip install --no-cache-dir pytest pytest-asyncio kubernetes

# Copy test utilities (not full test suite - that's mounted)
COPY styrened/tests/k8s/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create directories for RNS and styrene data
RUN mkdir -p /root/.styrene /root/.reticulum

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    RNS_LOGLEVEL=4 \
    STYRENE_CONFIG_DIR=/root/.styrene

# Entrypoint
ENTRYPOINT ["/entrypoint.sh"]
CMD ["styrened"]
