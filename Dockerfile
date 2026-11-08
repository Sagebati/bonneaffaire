# bonneaffaire MCP server image (x86-64, e.g. Synology DS920+). See docs/deployment.md.
# Dependencies come from uv.lock, so Providers that add dependencies need no change here.

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
# Dependencies first, in their own layer, so code changes rebuild quickly.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM python:3.14-slim-bookworm
RUN useradd --system --uid 1000 --no-create-home bonneaffaire
COPY --from=build --chown=bonneaffaire:bonneaffaire /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    BONNEAFFAIRE_HOST=0.0.0.0 \
    BONNEAFFAIRE_PORT=8000
USER bonneaffaire
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('BONNEAFFAIRE_PORT', '8000')}/health\", timeout=4)"]
CMD ["bonneaffaire", "serve"]
