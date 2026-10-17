FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .

RUN useradd --create-home --uid 1000 app
USER app

# API service default. The dashboard service overrides the start command in Railway.
CMD ["sh", "-c", "exec uvicorn api.webhooks:build_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
