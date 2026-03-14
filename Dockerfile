# ══════════════════════════════════════════════════════════════════
# Dockerfile — Production multi-stage build
#
# Stage 1 (builder): Install dependencies in isolated environment
# Stage 2 (runtime): Copy only what's needed — smaller final image
#
# Multi-stage builds are a production best practice:
#   - Separates build tools from runtime image
#   - Final image has no pip, no compilers — just your app
#   - Smaller images = faster pulls, smaller attack surface
#
# Build:  docker build -t deep-research-agent .
# Run:    docker run -p 8080:8080 --env-file .env deep-research-agent
# ══════════════════════════════════════════════════════════════════

# ── Stage 1: Builder ──────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (Docker layer caching — only re-runs pip install
# if requirements.txt changes, not every time your code changes)
COPY requirements.txt .

# Install to a prefix directory we'll copy to final stage
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Runtime ──────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Create non-root user (security best practice)
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --chown=appuser:appuser . .

# Create output directory
RUN mkdir -p output && chown appuser:appuser output

# Switch to non-root user
USER appuser

# ── Environment ──────────────────────────────────────────────────
# Cloud Run sets PORT automatically — we read it below
ENV PYTHONUNBUFFERED=1  
# Unbuffered output — print() shows up immediately in Cloud Run logs

ENV PYTHONDONTWRITEBYTECODE=1
# Don't write .pyc files — saves disk space

# ── Port ─────────────────────────────────────────────────────────
# Cloud Run requires port 8080 by default
EXPOSE 8080

# ── Health check ─────────────────────────────────────────────────
# Docker will mark container unhealthy if /health fails
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" \
    || exit 1

# ── Start command ─────────────────────────────────────────────────
# $PORT is set by Cloud Run (usually 8080)
# --workers 1: Research jobs are heavy — 1 worker is enough for Cloud Run
# --timeout 300: Research takes up to 5 mins — don't kill the request early
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --timeout-keep-alive 300"]
