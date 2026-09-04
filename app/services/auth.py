from sqlalchemy import select

from app.models import (
    TelegramUser,
    UserRole,
)

from app.db.session import SessionLocal


async def ensure_bootstrap_owner(session, telegram_id: int):

    """
    Автоматическое восстановление владельца.

    Если в системе нет ни одного OWNER —
    первый пользователь, который открыл бота,
    становится владельцем.
    """


    owner = (
        await session.execute(
            select(TelegramUser)
            .where(
                TelegramUser.role ==
                UserRole.OWNER.value
            )
            .where(
                TelegramUser.active.is_(True)
            )
        )
    ).scalar_one_or_none()



    if owner:

        existing = (
            await session.execute(
                select(TelegramUser)
                .where(
                    TelegramUser.telegram_id ==
                    telegram_id
                )
            )
        ).scalar_one_or_none()


        return existing



    user = (
        await session.execute(
            select(TelegramUser)
            .where(
                TelegramUser.telegram_id ==
                telegram_id
            )
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
        select(TelegramUser)
        .where(
            TelegramUser.telegram_id ==
            telegram_id
        )
    )

    return result.scalar_one_or_none()


async def get_access(message):

    if not message.from_user:
        return None

    async with SessionLocal() as session:

        user = await get_telegram_user(
            session,
            message.from_user.id,
        )

        if user is None or not user.active:
            return None

        return user