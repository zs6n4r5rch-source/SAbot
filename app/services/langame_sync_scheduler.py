import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func

from app.db.session import SessionLocal
from app.models import LangameSyncLog
from app.services.langame import langame_client

logger = logging.getLogger(__name__)


async def _run_one(sync_type: str, loader) -> None:
    started = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        row = LangameSyncLog(sync_type=sync_type, started_at=started, status="running", records_count=0)
        session.add(row)
        await session.commit()
        sync_id = row.id
    try:
        data = await loader()
        records = _count_records(data)
        finished = datetime.now(timezone.utc)
        async with SessionLocal() as session:
            row = await session.get(LangameSyncLog, sync_id)
            if row:
                row.finished_at = finished
                row.status = "success"
                row.records_count = records
                row.error = None
                await session.commit()
        logger.info("LANGAME read-only verification %s completed: %s records", sync_type, records)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        async with SessionLocal() as session:
            row = await session.get(LangameSyncLog, sync_id)
            if row:
                row.finished_at = datetime.now(timezone.utc)
                row.status = "failed"
                row.records_count = 0
                row.error = str(exc)[:4000]
                await session.commit()
        logger.exception("LANGAME read-only verification %s failed", sync_type)


def _count_records(data) -> int:
    if isinstance(data, list):
        return len(data)
    if not isinstance(data, dict):
        return 0
    for key in ("items", "data", "results", "records", "rows"):
        value = data.get(key)
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            for nested in ("items", "data", "results", "records", "rows"):
                nested_value = value.get(nested)
                if isinstance(nested_value, list):
                    return len(nested_value)
    return 1 if data else 0


def _window(days: int = 1) -> tuple[str, str]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    return start.date().isoformat(), end.date().isoformat()


async def langame_verification_sync_once() -> None:
    """Verify every production LANGAME contour used by the application.

    This job intentionally never writes to LANGAME and never treats a successful
    HTTP response as a valid payload without parsing its JSON shape. PostgreSQL
    stores only the audit outcome/count; LANGAME remains the source of truth.
    """
    date_from, date_to = _window(1)
    jobs = (
        ("clubs", langame_client.clubs),
        ("users", langame_client.users),
        ("shifts", langame_client.shifts),
        ("products", langame_client.products),
        ("balances", langame_client.balances),
        ("guest_groups", langame_client.guest_groups),
        ("guest_sessions", lambda: langame_client.guest_sessions(date_from, date_to)),
        ("transactions", lambda: langame_client.transactions(date_from, date_to)),
        ("operations_log", lambda: langame_client.all_operations_log(date_from, date_to)),
        ("product_sales", lambda: langame_client.product_sales(date_from, date_to)),
        ("product_arrivals", lambda: langame_client.product_arrivals(date_from, date_to)),
    )
    for sync_type, loader in jobs:
        await _run_one(sync_type, loader)
        await asyncio.sleep(0)


async def langame_sync_scheduler(interval_seconds: int = 900) -> None:
    """Continuously audit the health/shape of all LANGAME read-only datasets."""
    while True:
        try:
            await langame_verification_sync_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("LANGAME verification scheduler iteration failed")
        await asyncio.sleep(interval_seconds)
