from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import CampaignStatus, MarketingCampaign, TelegramUser, UserRole

router = Router()


async def _is_owner(message: Message) -> bool:
    if not message.from_user:
        return False
    async with SessionLocal() as session:
        user = await session.scalar(select(TelegramUser).where(TelegramUser.telegram_id == message.from_user.id))
        return bool(user and user.active and user.role == UserRole.OWNER.value)


@router.message(Command("mail_schedule"))
async def schedule_mailing(message: Message):
    if not await _is_owner(message):
        await message.answer("⛔ Доступ только для владельца.")
        return
    parts = (message.text or "").split(maxsplit=3)
    if len(parts) != 4:
        await message.answer("Формат: /mail_schedule ID YYYY-MM-DD HH:MM\nВремя указывается по Europe/Moscow.")
        return
    try:
        campaign_id = int(parts[1])
        local_dt = datetime.strptime(f"{parts[2]} {parts[3]}", "%Y-%m-%d %H:%M")
        scheduled_at = local_dt.replace(tzinfo=ZoneInfo("Europe/Moscow")).astimezone(ZoneInfo("UTC"))
    except (ValueError, ZoneInfoNotFoundError):
        await message.answer("⛔ Некорректные дата/время. Используйте YYYY-MM-DD HH:MM.")
        return
    async with SessionLocal() as session:
        campaign = await session.get(MarketingCampaign, campaign_id)
        if campaign is None:
            await message.answer("Кампания не найдена.")
            return
        if campaign.status != CampaignStatus.DRAFT.value:
            await message.answer(f"⛔ Кампания уже имеет статус: {campaign.status}.")
            return
        campaign.status = CampaignStatus.SCHEDULED.value
        campaign.scheduled_at = scheduled_at
        campaign.confirmed_by = message.from_user.id
        campaign.confirmed_at = datetime.now(ZoneInfo("UTC"))
        await session.commit()
    await message.answer(f"⏰ Кампания #{campaign_id} запланирована на {local_dt:%Y-%m-%d %H:%M} Europe/Moscow.")
