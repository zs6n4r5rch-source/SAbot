import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import CampaignStatus, MarketingCampaign
from app.bot.mailing import _send_campaign

logger = logging.getLogger(__name__)


async def dispatch_due_campaigns(bot: Bot) -> int:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        campaigns = (
            await session.execute(
                select(MarketingCampaign)
                .where(
                    MarketingCampaign.status == CampaignStatus.SCHEDULED.value,
                    MarketingCampaign.scheduled_at.is_not(None),
                    MarketingCampaign.scheduled_at <= now,
                )
                .order_by(MarketingCampaign.scheduled_at, MarketingCampaign.id)
                .limit(10)
            )
        ).scalars().all()
        ids = []
        for campaign in campaigns:
            campaign.status = CampaignStatus.RUNNING.value
            ids.append(campaign.id)
        if ids:
            await session.commit()
    for campaign_id in ids:
        try:
            await _send_campaign(bot, campaign_id, 0)
        except Exception:
            logger.exception("Scheduled marketing campaign %s failed", campaign_id)
            async with SessionLocal() as session:
                campaign = await session.get(MarketingCampaign, campaign_id)
                if campaign and campaign.status == CampaignStatus.RUNNING.value:
                    campaign.status = CampaignStatus.CANCELLED.value
                    await session.commit()
    return len(ids)


async def marketing_scheduler(bot: Bot, interval_seconds: int = 30) -> None:
    while True:
        try:
            await dispatch_due_campaigns(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Marketing scheduler iteration failed")
        await asyncio.sleep(interval_seconds)
