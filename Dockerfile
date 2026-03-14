# ─── Stage 1: Builder ────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools
RUN pip install --upgrade pip build

# Copy project files needed for installation
COPY pyproject.toml README.md LICENSE ./
COPY flowlens/ ./flowlens/

# Build the wheel (production deps only — no [dev] extras)
RUN pip wheel --no-cache-dir --wheel-dir /wheels .


# ─── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Security: run as a non-root user
RUN groupadd --system flowlens && \
    useradd --system --gid flowlens --create-home --home-dir /home/flowlens flowlens

WORKDIR /app

# Install the pre-built wheel (no build tools in the final image)
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels flowlens && \
    rm -rf /wheels

# Create a writable directory for the SQLite database
RUN mkdir -p /data && chown flowlens:flowlens /data

# Switch to non-root user
USER flowlens

# Expose the FlowLens server port
EXPOSE 8585

# Health check — calls the /health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8585/health')" || exit 1

# Default environment variables (can be overridden at runtime)
ENV FLOWLENS_DB_PATH=/data/flowlens.db \
    FLOWLENS_HOST=0.0.0.0 \
    FLOWLENS_PORT=8585

CMD ["python", "-m", "uvicorn", "flowlens.server.app:create_app", \
     "--factory", \
     "--host", "0.0.0.0", \
     "--port", "8585"]
