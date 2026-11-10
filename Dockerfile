FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8000 \
    FASTEMBED_CACHE_PATH=/opt/fastembed \
    HF_HUB_DISABLE_TELEMETRY=1

# Dependencies first, for layer caching.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# Bake the embedding model into the image (ADR 0003); the index itself is built at startup.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"
ENV HF_HUB_OFFLINE=1

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# Run as a non-root user. The index dir exists in the image owned by `app`, so a
# fresh named volume mounted there (docker-compose.yml) inherits that ownership.
RUN useradd --system --uid 10001 --user-group --no-create-home app \
    && mkdir -p /app/chroma \
    && chown app:app /app/chroma \
    && chmod -R a+rX "$FASTEMBED_CACHE_PATH"
USER app

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
