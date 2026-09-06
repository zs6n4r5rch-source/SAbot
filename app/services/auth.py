from sqlalchemy import select

from app.models import TelegramUser
from app.db.session import SessionLocal


async def get_telegram_user(session, telegram_id: int):
    result = await session.execute(
        select(TelegramUser).where(TelegramUser.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def get_access(message):
    if not message.from_user:
        return None

    async with SessionLocal() as session:
        user = await get_telegram_user(session, message.from_user.id)
        if user is None or not user.active:
            return None
        return user
