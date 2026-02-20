# Local development image for mesh integration tests.
#
# Builds styrened from the repo source so tests run against the current
# code — not the (potentially stale) GHCR release image. This ensures
# all IPC handlers, FTS5 indexing, and protocol fixes are present.
#
# Build context must be the styrened repo root:
#   docker build -f tests/mesh/Dockerfile -t styrened-mesh-dev .

FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install dependencies first for layer caching
COPY pyproject.toml setup.cfg* ./
COPY src/ src/
RUN pip install --no-cache-dir .

# Verify installation
RUN styrened --version

ENV HOME=/root
ENV PYTHONUNBUFFERED=1

CMD ["styrened", "daemon"]
