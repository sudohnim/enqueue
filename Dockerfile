FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/ ./src/

RUN uv sync --frozen --no-dev --extra hosted

EXPOSE 8000

# --no-sync: run what the build installed. A plain `uv run` re-syncs to the default
# groups at every start, which put the dev tools (crawl4ai's browser, scipy) into
# the container and took the hosted extra back out.
CMD sh -c 'uv run --no-sync enq relay --host 0.0.0.0 --port ${PORT:-8788}'
