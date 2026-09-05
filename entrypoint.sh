#!/bin/sh
set -e

echo "Ensuring database schema exists (create-if-missing)..."
python <<'PYEOF'
import asyncio
from app.db.session import engine
from app.models.base import Base

async def _create():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

asyncio.run(_create())
PYEOF

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

echo "Marking Alembic revision as up to date..."
alembic stamp head

echo "Starting bot..."
exec python -m app.main
