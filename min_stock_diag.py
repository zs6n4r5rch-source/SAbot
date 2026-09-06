import asyncio
import os
import subprocess
import sys

import asyncpg

RAW_URL = os.environ["DATABASE_URL"]
ASYNCPG_URL = RAW_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
OUTPUT = "min-stock-diagnostic.txt"


async def verify_after_migration() -> list[str]:
    conn = await asyncpg.connect(ASYNCPG_URL)
    try:
        version = await conn.fetchval("SELECT version_num FROM alembic_version")
        regclass = await conn.fetchval("SELECT to_regclass('public.inventory_balances')")
        default = await conn.fetchval(
            """
            SELECT column_default
            FROM information_schema.columns
            WHERE table_schema='public'
              AND table_name='inventory_balances'
              AND column_name='min_stock'
            """
        )
        return [
            f"alembic_version = {version}",
            f"to_regclass(public.inventory_balances) = {regclass}",
            f"inventory_balances.min_stock.column_default = {default}",
        ]
    finally:
        await conn.close()


def run() -> int:
    lines: list[str] = []
    lines.append("=== Alembic post-close acceptance ===")
    lines.append("Migration is executed through the normal Alembic env.py in a subprocess.")
    lines.append("")

    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    lines.append("$ alembic upgrade head")
    lines.append(result.stdout.rstrip())
    if result.stderr:
        lines.append("[stderr]")
        lines.append(result.stderr.rstrip())
    lines.append(f"exit code = {result.returncode}")

    if result.returncode != 0:
        lines.append("RESULT = FAIL (migration returned non-zero exit code)")
    else:
        lines.append("")
        lines.append("The migration subprocess has exited; its Alembic connection/engine is closed.")
        lines.append("Opening a new independent asyncpg connection for verification...")
        try:
            checks = asyncio.run(verify_after_migration())
            lines.extend(checks)
            lines.append("")
            if checks[0] != "alembic_version = 0025_inventory_min_stock_reconciliation":
                raise AssertionError("unexpected alembic_version")
            if checks[1] != "to_regclass(public.inventory_balances) = inventory_balances":
                raise AssertionError("inventory_balances table is missing")
            if checks[2] != "inventory_balances.min_stock.column_default = 5":
                raise AssertionError("inventory_balances.min_stock default is not 5")
            lines.append("RESULT = PASS")
        except Exception as exc:
            lines.append(f"RESULT = FAIL ({type(exc).__name__}: {exc})")

    text = "\n".join(lines) + "\n"
    with open(OUTPUT, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(text, flush=True)

    return 0 if lines[-1] == "RESULT = PASS" else 1


if __name__ == "__main__":
    sys.exit(run())
