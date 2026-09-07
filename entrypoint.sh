#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head

echo "Starting bot..."
exec python -m app.main
