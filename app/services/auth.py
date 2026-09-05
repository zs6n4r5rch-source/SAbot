from sqlalchemy import select

from app.config import settings
from app.models import TelegramUser, UserRole
from app.db.session import SessionLocal


async def ensure_bootstrap_owner(session, telegram_id: int):
    """Return/create an owner only when the Telegram ID is explicitly configured.

    The old implementation promoted the first Telegram user to owner when the
    database had no owners. That is unsafe in production: an unknown user must
    never gain owner privileges merely because the database is empty.
    """
    if telegram_id not in settings.owners:
        return None

    user = (
        await session.execute(
            select(TelegramUser).where(TelegramUser.telegram_id == telegram_id)
        )
    ).scalar_one_or_none()

    if user is None:
        user = TelegramUser(
            telegram_id=telegram_id,
            role=UserRole.OWNER.value,
            active=True,
        )
        session.add(user)
    else:
        user.role = UserRole.OWNER.value
        user.active = True

    await session.commit()
    await session.refresh(user)
    return user


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
