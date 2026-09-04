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

echo "Marking Alembic revision as up to date..."
alembic stamp head

echo "Starting bot..."
exec python -m app.main
