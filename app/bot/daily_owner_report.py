import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import FSInputFile
from sqlalchemy import select

from app.config import settings
from app.db.session import SessionLocal
from app.models import OwnerDailyReportDelivery, OwnerReportSettings, TelegramUser, UserRole
from app.services.audit import write_audit
from app.bot.analytics import daily_report_for_window
from app.bot.analytics_export import build_excel

logger = logging.getLogger(__name__)


def report_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.report_timezone)
    except Exception:
        logger.warning("Invalid REPORT_TIMEZONE=%s, using Europe/Moscow", settings.report_timezone)
        return ZoneInfo("Europe/Moscow")


async def configured_owners() -> list[OwnerReportSettings]:
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(OwnerReportSettings).where(OwnerReportSettings.enabled.is_(True))
        )).scalars().all()
        known = {r.owner_telegram_id for r in rows}
        # Bootstrap owners from env are auto-provisioned with default settings.
        for owner_id in settings.owners - known:
            row = OwnerReportSettings(owner_telegram_id=owner_id)
            session.add(row)
            rows.append(row)
        await session.commit()
        return rows


async def all_owner_settings() -> list[OwnerReportSettings]:
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(OwnerReportSettings).order_by(OwnerReportSettings.owner_telegram_id)
        )).scalars().all()
        existing = {r.owner_telegram_id for r in rows}
        for owner_id in settings.owners - existing:
            row = OwnerReportSettings(owner_telegram_id=owner_id)
            session.add(row)
            rows.append(row)
        await session.commit()
        return rows


async def send_daily_report(bot: Bot, report_date, owner_telegram_id: int | None = None) -> None:
    owner_settings = await configured_owners()
    if owner_telegram_id is not None:
        owner_settings = [x for x in owner_settings if x.owner_telegram_id == owner_telegram_id]
    if not owner_settings:
        logger.warning("No enabled owners configured; daily report skipped")
        return

    # Each owner may have a different timezone/content selection.

    for cfg in owner_settings:
        tz = ZoneInfo(cfg.report_timezone)
        local_start = datetime.combine(report_date, datetime.min.time(), tzinfo=tz)
        local_end = local_start + timedelta(days=1)
        start = local_start.astimezone(timezone.utc)
        end = local_end.astimezone(timezone.utc)
        text = await daily_report_for_window(
            start, end, f"{report_date:%d.%m.%Y}",
            include_sales=cfg.include_sales, include_shifts=cfg.include_shifts,
            include_inventory=cfg.include_inventory, include_discrepancies=cfg.include_discrepancies,
            include_salary=cfg.include_salary, include_clients=cfg.include_clients,
        )
        path: Path | None = None
        try:
            if cfg.send_excel:
                path = await build_excel(start=start, end=end)
            async with SessionLocal() as session:
                existing = (await session.execute(
                    select(OwnerDailyReportDelivery).where(
                        OwnerDailyReportDelivery.report_date == report_date,
                        OwnerDailyReportDelivery.owner_telegram_id == cfg.owner_telegram_id,
                    )
                )).scalar_one_or_none()
                if existing and existing.status == "sent":
                    continue
                if existing is None:
                    existing = OwnerDailyReportDelivery(report_date=report_date, owner_telegram_id=cfg.owner_telegram_id, status="sending")
                    session.add(existing)
                    await session.flush()
                else:
                    existing.status = "sending"
                    existing.error = None
                await session.commit()
            try:
                await bot.send_message(cfg.owner_telegram_id, text)
                if path:
                    await bot.send_document(cfg.owner_telegram_id, FSInputFile(path), caption=f"📊 Excel-отчёт за {report_date:%d.%m.%Y}")
                async with SessionLocal() as session:
                    row = (await session.execute(
                        select(OwnerDailyReportDelivery).where(
                            OwnerDailyReportDelivery.report_date == report_date,
                            OwnerDailyReportDelivery.owner_telegram_id == cfg.owner_telegram_id,
                        )
                    )).scalar_one()
                    row.status = "sent"
                    row.sent_at = datetime.now(timezone.utc)
                    await session.commit()
                    await write_audit(session, actor_telegram_id=cfg.owner_telegram_id, action="daily_report_sent", entity_type="owner_daily_report", entity_id=str(report_date), payload={"report_date": report_date.isoformat()})
            except Exception as exc:
                logger.exception("Daily report failed for owner %s", cfg.owner_telegram_id)
                async with SessionLocal() as session:
                    row = (await session.execute(
                        select(OwnerDailyReportDelivery).where(
                            OwnerDailyReportDelivery.report_date == report_date,
                            OwnerDailyReportDelivery.owner_telegram_id == cfg.owner_telegram_id,
                        )
                    )).scalar_one_or_none()
                    if row:
                        row.status = "failed"
                        row.error = str(exc)[:2000]
                        await session.commit()
        finally:
            if path:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


async def daily_report_scheduler(bot: Bot) -> None:
    """Run once per minute and send yesterday's report at configured local time."""
    last_keys: set[tuple[int, str]] = set()
    while True:
        try:
            configs = await all_owner_settings()
            for cfg in configs:
                if not cfg.enabled:
                    continue
                try:
                    tz = ZoneInfo(cfg.report_timezone)
                except Exception:
                    tz = report_timezone()
                now = datetime.now(tz)
                key = f"{now:%Y-%m-%d}"
                marker = (cfg.owner_telegram_id, key)
                if now.hour == cfg.report_hour and now.minute == cfg.report_minute and marker not in last_keys:
                    last_keys.add(marker)
                    try:
                        await send_daily_report(bot, (now - timedelta(days=1)).date(), owner_telegram_id=cfg.owner_telegram_id)
                    except Exception:
                        logger.exception("Daily owner report crashed")
        except Exception:
            logger.exception("Daily report scheduler configuration check failed")
        await asyncio.sleep(30)
