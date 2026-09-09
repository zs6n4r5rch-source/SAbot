import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

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
        logger.info("LANGAME verification sync %s completed: %s records", sync_type, records)
    except Exception as exc:
        async with SessionLocal() as session:
            row = await session.get(LangameSyncLog, sync_id)
            if row:
                row.finished_at = datetime.now(timezone.utc)
                row.status = "failed"
                row.error = str(exc)[:4000]
                await session.commit()
        logger.exception("LANGAME verification sync %s failed", sync_type)


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
            for nested in ("items", "results", "records", "rows"):
                if isinstance(value.get(nested), list):
                    return len(value[nested])
    return 1 if data else 0


async def langame_verification_sync_once() -> None:
    jobs = (
        ("clubs", langame_client.clubs),
        ("users", langame_client.users),
        ("shifts", langame_client.shifts),
        ("products", langame_client.products),
        ("guest_groups", langame_client.guest_groups),
    )
    for sync_type, loader in jobs:
        await _run_one(sync_type, loader)
        await asyncio.sleep(0)


async def langame_sync_scheduler(interval_seconds: int = 900) -> None:
    """Continuously audit the health/shape of LANGAME read-only datasets.

    This is deliberately read-only: it records the response count and outcome in
    PostgreSQL without changing anything in LANGAME.
    """
    while True:
        try:
            await langame_verification_sync_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("LANGAME verification scheduler iteration failed")
        await asyncio.sleep(interval_seconds)
