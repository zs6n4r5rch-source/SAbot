import asyncio
import os

import asyncpg


def test_inventory_min_stock_server_default_is_five_after_migrations():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise AssertionError("DATABASE_URL is required for the schema contract test")

    async def check_schema():
        url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        conn = await asyncpg.connect(url)
        try:
            row = await conn.fetchrow(
                """
                SELECT column_default, data_type, numeric_precision, numeric_scale
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'inventory_balances'
                  AND column_name = 'min_stock'
                """
            )
        finally:
            await conn.close()

        assert row is not None, "inventory_balances.min_stock must exist"
        assert row["data_type"] == "numeric"
        assert row["numeric_precision"] == 14
        assert row["numeric_scale"] == 3
        assert row["column_default"] == "5"

    asyncio.run(check_schema())
