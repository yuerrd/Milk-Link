#!/bin/sh
set -e

echo "[entrypoint] Running Alembic migrations..."
uv run alembic upgrade head

echo "[entrypoint] Starting Uvicorn..."
exec uv run uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level info
