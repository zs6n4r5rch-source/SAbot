#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head

echo "Starting SAbot unified runtime..."
exec python -m app.main
