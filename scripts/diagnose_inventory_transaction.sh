#!/usr/bin/env bash
set -euo pipefail

PGURL="$(printf '%s' "$DATABASE_URL" | sed 's#^postgresql+asyncpg://#postgresql://#')"

echo "=== Alembic transaction diagnostic ==="
echo "search_path / schema before migrations:"
psql "$PGURL" -v ON_ERROR_STOP=1 -c "SHOW search_path; SELECT current_schema();"

check() {
  local label="$1"
  echo "=== ${label} ==="
  psql "$PGURL" -v ON_ERROR_STOP=1 -t -A -F '|' -c "
    SELECT 'alembic_version', COALESCE(string_agg(version_num, ',' ORDER BY version_num), '<empty>')
    FROM alembic_version;
    SELECT 'to_regclass', COALESCE(to_regclass('inventory_balances')::text, '<null>');
    SELECT 'public_table', COALESCE((SELECT 'present' FROM pg_tables WHERE schemaname='public' AND tablename='inventory_balances'), 'absent');
    SELECT 'min_stock_default', COALESCE((SELECT column_default FROM information_schema.columns WHERE table_schema='public' AND table_name='inventory_balances' AND column_name='min_stock'), '<no column>');
  "
done

echo "--- upgrade 0001 ---"
alembic upgrade 0001_initial
check "after 0001"

echo "--- upgrade 0021 ---"
alembic upgrade 0021_inventory_min_stock_five
check "after 0021"

echo "--- upgrade 0024 ---"
alembic upgrade 0024_bonus_record_source
check "after 0024"
echo "--- upgrade 0025 ---"
alembic upgrade 0025_inventory_min_stock_reconciliation
check "after 0025"
