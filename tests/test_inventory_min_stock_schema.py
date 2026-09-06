import asyncio
import os

import asyncpg


def test_inventory_min_stock_server_default_is_five_after_migrations():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise AssertionError("DATABASE_URL is required for the schema contract test")

    async def check_default():
        url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        conn = await asyncpg.connect(url)
        try:
            default = await conn.fetchval(
                """
                SELECT column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'inventory_balances'
                  AND column_name = 'min_stock'
                """
            )
        finally:
            await conn.close()

        assert default is not None, "inventory_balances.min_stock must have a DB default"
        assert default.strip() in {"5", "5::integer"}, (
            "inventory_balances.min_stock DB default must be 5, "
            f"got {default!r}"
        )

    asyncio.run(check_default())
