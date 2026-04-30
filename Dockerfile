# ============================================================
# Betfair Automation - Production Dockerfile
# Multi-stage build for optimal image size and layer caching
# ============================================================

# Stage 1: Dependencies
FROM python:3.11-slim AS deps

WORKDIR /app

# Install build dependencies for any C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies in isolated environment
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Builder (for any compilation steps)
FROM deps AS builder

RUN pip install --no-cache-dir --prefix=/install --no-deps -r requirements.txt

# Stage 3: Production image
FROM python:3.11-slim AS runner

LABEL org.opencontainers.image.title="Betfair Automation"
LABEL org.opencontainers.image.description="Automated Betfair trading with paper trading mode"
LABEL org.opencontainers.image.version="1.0.0"

WORKDIR /app

# Create non-root user for security
RUN groupadd --gid 10001 betfair && \
    useradd --uid 10001 --gid betfair --shell /bin/bash --create-home betfair

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy installed Python packages from builder stage
COPY --from=builder /install /usr/local

# Copy application code
COPY *.py ./
COPY config/ ./config/
COPY scripts/ ./scripts/ 2>/dev/null || true

# Create data directory with proper permissions
RUN mkdir -p /app/data && chown -R betfair:betfair /app

# Create certificates directory
RUN mkdir -p /app/certs && chown betfair:betfair /app/certs

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    BETFAIR_USERNAME="" \
    BETFAIR_PASSWORD="" \
    BETFAIR_APP_KEY="" \
    BETFAIR_CERTS_PATH="/app/certs"

# Expose port (if HTTP server is added)
EXPOSE 8000

# Healthcheck - verify the container can import its modules
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3 -c "import betfair_cli, signal_engine, paper_trader; print('OK')" || exit 1

# Switch to non-root user
USER betfair

# Use tini for proper signal handling
ENTRYPOINT ["/usr/bin/tini", "--"]

# Default command: run trading cycle
CMD ["python3", "betfair_cli.py", "run"]