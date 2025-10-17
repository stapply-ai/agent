# syntax=docker/dockerfile:1

# Stage 1: Base system dependencies (rarely changes)
FROM python:3.12-slim AS system-deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# System deps for Playwright/Chromium (cached separately)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    tini \
    # Browser dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libxss1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Stage 2: Python dependencies (changes less frequently)
FROM system-deps AS python-deps

WORKDIR /app

# Copy only dependency files first for better caching
COPY pyproject.toml README.md /app/

# Install uv (fast Python installer) and dependencies
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    /root/.local/bin/uv sync --no-dev

# Install Playwright browsers (cached with Python deps)
RUN /root/.local/bin/uv run playwright install chromium

# Stage 3: Application (changes most frequently)
FROM python-deps AS app

ENV UVICORN_WORKERS=2 \
    PORT=8080

# Copy the application code (this invalidates cache when code changes)
COPY server /app/server

# Create a non-root user
RUN useradd -m app && chown -R app:app /app
USER app

EXPOSE 8080

# Use tini as PID 1 for proper signal handling
ENTRYPOINT ["/usr/bin/tini", "--"]

# Start uvicorn with the ASGI app
CMD ["/app/.venv/bin/uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8080"]


