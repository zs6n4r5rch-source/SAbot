#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head

echo "Ensuring Alembic version column can hold current revision IDs..."
python <<'PYEOF'
import asyncio
from sqlalchemy import text
from app.db.session import engine

async def _widen_version_column():
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)"
        ))

asyncio.run(_widen_version_column())
PYEOF

echo "Starting bot..."
exec python -m app.main
