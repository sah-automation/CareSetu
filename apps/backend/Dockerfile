# syntax=docker/dockerfile:1
# CareSetu backend container for Cloud Run (asia-south1 / Mumbai).
# Multi-stage: build Python deps with uv, then run from a slim image.
FROM python:3.13-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --compile-bytecode

FROM python:3.13-slim AS runtime
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=builder /app/.venv /app/.venv
COPY . /app
EXPOSE 8080
# Cloud Run sets $PORT; shell form expands it at startup.
# --max-instances=1 in the deploy keeps exactly one in-process dispatcher loop.
CMD .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
