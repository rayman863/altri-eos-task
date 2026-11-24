# syntax=docker/dockerfile:1
FROM python:3.12.16-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir uv==0.13.9

WORKDIR /app

# Dependencies first, so code edits don't invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# The seed file lives at the repo root; compose mounts it read-only at /seed.
RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000

# API_WORKERS stays 1 until platform layer L1 (plan section 5).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${API_WORKERS:-1} --no-access-log --timeout-graceful-shutdown 20"]
