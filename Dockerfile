# --- Build stage: install dependencies with uv into a self-contained venv ---
FROM python:3.11-slim AS builder

# uv binary from the official distroless image.
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first (cached layer) using the lockfile only.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- Runtime stage ---
FROM python:3.11-slim

WORKDIR /app

# Bring the virtualenv and application code over.
COPY --from=builder /app/.venv /app/.venv
COPY src ./src
COPY scripts ./scripts
COPY pyproject.toml uv.lock ./

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONUNBUFFERED=1 \
    PORT=8080

EXPOSE 8080

# Cloud Run sets $PORT; default to 8080 locally.
CMD ["sh", "-c", "uvicorn server:app --app-dir src --host 0.0.0.0 --port ${PORT}"]
