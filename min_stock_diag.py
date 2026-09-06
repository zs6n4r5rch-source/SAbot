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
LOG_PATH = "min-stock-diagnostic.txt"


def log(message: str) -> None:
    print(message, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(message + "\n")


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
        log(f"--- checkpoint: {label} ---")
        log(f"search_path      = {search_path}")
        log(f"current_schema   = {current_schema}")
        log(f"to_regclass      = {regclass}")
        log(f"alembic_version  = {versions}")
        log("---")
    finally:
        await conn.close()


def run_upgrade(revision: str) -> None:
    log(f"$ alembic upgrade {revision}")
    result = subprocess.run(
        ["alembic", "upgrade", revision],
        capture_output=True,
        text=True,
    )
    if result.stdout:
        log(result.stdout.rstrip())
    if result.stderr:
        log(result.stderr.rstrip())
    log(f"exit code = {result.returncode}")
    if result.returncode != 0:
        raise SystemExit(result.returncode)


async def main() -> None:
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)
    await checkpoint("before any migration")
    for rev in REVISIONS:
        run_upgrade(rev)
        await checkpoint(f"after {rev}")


if __name__ == "__main__":
    asyncio.run(main())
