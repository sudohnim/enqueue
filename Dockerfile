FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/ ./src/

RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD sh -c 'uv run enq relay --host 0.0.0.0 --port ${PORT:-8788}'
