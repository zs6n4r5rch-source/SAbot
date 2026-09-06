import asyncio
import os
import subprocess
import sys

import asyncpg

RAW_URL = os.environ["DATABASE_URL"]
ASYNCPG_URL = RAW_URL.replace("postgresql+asyncpg://", "postgresql://", 1)

REVISIONS = [
    "0001_initial",
    "0021_inventory_min_stock_five",
    "0024_bonus_record_source",
    "0025_inventory_min_stock_reconciliation",
]


async def checkpoint(label: str) -> None:
    conn = await asyncpg.connect(ASYNCPG_URL)
    try:
        search_path = await conn.fetchval("SHOW search_path")
        current_schema = await conn.fetchval("SELECT current_schema()")
        regclass = await conn.fetchval("SELECT to_regclass('inventory_balances')")

        try:
            version_rows = await conn.fetch("SELECT * FROM alembic_version")
            versions = [dict(r) for r in version_rows]
        except asyncpg.exceptions.UndefinedTableError:
            versions = "alembic_version table does not exist"

        print(f"--- checkpoint: {label} ---")
        print(f"search_path      = {search_path}")
        print(f"current_schema   = {current_schema}")
        print(f"to_regclass      = {regclass}")
        print(f"alembic_version  = {versions}")
        print("---", flush=True)
    finally:
        await conn.close()


def run_upgrade(revision: str) -> None:
    result = subprocess.run(
        ["alembic", "upgrade", revision],
        capture_output=True,
        text=True,
    )
    print(f"$ alembic upgrade {revision}")
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
    print(f"exit code = {result.returncode}", flush=True)


async def main() -> None:
    await checkpoint("before any migration")
    for rev in REVISIONS:
        run_upgrade(rev)
        await checkpoint(f"after {rev}")


if __name__ == "__main__":
    asyncio.run(main())
