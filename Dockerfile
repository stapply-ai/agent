# syntax=docker/dockerfile:1

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UVICORN_WORKERS=2 \
    PORT=8080

# System deps for Playwright/Chromium if needed later; keep minimal by default
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only dependency files first for better caching
COPY pyproject.toml README.md /app/

# Install uv (fast Python installer)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    /root/.cargo/bin/uv venv && \
    . /app/.venv/bin/activate || true

# Install runtime dependencies
RUN /root/.cargo/bin/uv sync --no-dev

# Copy the application code
COPY server /app/server
COPY sample.py /app/sample.py

# Create a non-root user
RUN useradd -m app && chown -R app:app /app
USER app

EXPOSE 8080

# Use tini as PID 1 for proper signal handling
ENTRYPOINT ["/usr/bin/tini", "--"]

# Start uvicorn with the ASGI app
CMD ["/app/.venv/bin/uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8080"]


