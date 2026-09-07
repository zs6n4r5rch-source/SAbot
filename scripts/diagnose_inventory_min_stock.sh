#!/usr/bin/env bash
set -euo pipefail

check_default() {
  local label="$1"
  echo "=== ${label} ==="
  python - <<'PY'
import asyncio
import os
import asyncpg

async def main():
    url = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(url)
    try:
        row = await conn.fetchrow("""
            SELECT
                c.column_default,
                pg_get_expr(d.adbin, d.adrelid) AS pg_default_expr
            FROM information_schema.columns c
            LEFT JOIN pg_attribute a
              ON a.attrelid = 'public.inventory_balances'::regclass
             AND a.attname = c.column_name
            LEFT JOIN pg_attrdef d
              ON d.adrelid = a.attrelid
             AND d.adnum = a.attnum
            WHERE c.table_schema = 'public'
              AND c.table_name = 'inventory_balances'
              AND c.column_name = 'min_stock'
        """)
        print({"column_default": row["column_default"], "pg_default_expr": row["pg_default_expr"]})
    finally:
        await conn.close()

asyncio.run(main())
PY
}

alembic upgrade 0021_inventory_min_stock_five
check_default "after 0021"

alembic upgrade 0024_bonus_record_source
check_default "after 0024"

alembic upgrade 0025_inventory_min_stock_reconciliation
check_default "after 0025"
