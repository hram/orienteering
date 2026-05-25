FROM node:22-bookworm-slim AS claude-cli

RUN npm install -g @anthropic-ai/claude-code@latest && \
    npm cache clean --force


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000 \
    ORIENTEERING_PORTAL_DB_PATH=/data/orienteering/orienteering.sqlite3 \
    ORIENTEERING_PORTAL_UPLOAD_DIR=/data/orienteering/uploads \
    ORIENTEERING_PORTAL_MAP_DIR=/data/orienteering/maps \
    HOME=/data/orienteering \
    CLAUDE_CLI_PATH=/usr/local/bin/claude

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    addgroup --system app && \
    adduser --system --ingroup app --home /app app && \
    mkdir -p /data/orienteering/uploads /data/orienteering/maps && \
    chown -R app:app /app /data/orienteering

COPY --from=claude-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=claude-cli /usr/local/bin/claude /usr/local/bin/claude
COPY --from=claude-cli /usr/local/lib/node_modules/@anthropic-ai /usr/local/lib/node_modules/@anthropic-ai

COPY pyproject.toml README.md ./
COPY portal ./portal
COPY static ./static
COPY templates ./templates

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8000\")}/', timeout=3).read(1)"

CMD ["sh", "-c", "mkdir -p \"$(dirname \"$ORIENTEERING_PORTAL_DB_PATH\")\" \"$ORIENTEERING_PORTAL_UPLOAD_DIR\" \"$ORIENTEERING_PORTAL_MAP_DIR\" && uvicorn portal.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
