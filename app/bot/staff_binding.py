from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import (
    AccessProfile,
    Employee,
    TelegramBindingRequest,
    TelegramUser,
    UserRole,
)
from app.services.audit import write_audit
from app.services.staff_access import normalize_username


router = Router()


def review_kb(request_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"bind:approve:{request_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"bind:reject:{request_id}",
                ),
            ]
        ]
    )


async def notify_owners(bot, text: str, reply_markup=None):
    async with SessionLocal() as session:
        owners = (
            await session.execute(
                select(TelegramUser).where(
                    TelegramUser.role == UserRole.OWNER.value,
                    TelegramUser.active.is_(True),
                )
            )
        ).scalars().all()

    for owner in owners:
        try:
            await bot.send_message(
                owner.telegram_id,
                text,
                reply_markup=reply_markup,
            )
        except Exception:
            pass


async def process_staff_start(message: Message) -> bool:
    """
    Обработка /start для сотрудников.
    Возвращает True если старт был обработан.
    """

    if not message.from_user:
        return False

    username = normalize_username(message.from_user.username)

    if not username:
        return False


    async with SessionLocal() as session:

        profile = (
            await session.execute(
                select(AccessProfile).where(
                    AccessProfile.username == username,
                    AccessProfile.active.is_(True),
                )
            )
        ).scalar_one_or_none()


        if profile is None:
            from app.services.staff_access import ensure_staff_profile
            profile = await ensure_staff_profile(session, username)
            if profile is None:
                return False
            await session.flush()


        # Владелец получает доступ сразу
        if profile.role == UserRole.OWNER.value:

            from app.bot.keyboards import owner_menu

            user = (
                await session.execute(
                    select(TelegramUser).where(
                        TelegramUser.telegram_id == message.from_user.id
                    )
                )
            ).scalar_one_or_none()


            if user is None:
                user = TelegramUser(
                    telegram_id=message.from_user.id,
                    role=UserRole.OWNER.value,
                    active=True,
                )
                session.add(user)

            else:
                user.role = UserRole.OWNER.value
                user.active = True


            await session.commit()


            await message.answer(
                f"👑 <b>Доступ владельца активирован</b>\n\n"
                f"Профиль: <b>{profile.display_name}</b>\n"
                "Полный доступ к системе Strike Arena.",
                reply_markup=owner_menu(),
            )
            return True


        existing = (
            await session.execute(
                select(TelegramUser).where(
                    TelegramUser.telegram_id == message.from_user.id
                )
            )
        ).scalar_one_or_none()


        if existing and existing.active:
            return False



        pending = (
            await session.execute(
                select(TelegramBindingRequest).where(
                    TelegramBindingRequest.profile_id == profile.id,
                    TelegramBindingRequest.telegram_id == message.from_user.id,
                    TelegramBindingRequest.status == "pending",
                )
            )
        ).scalar_one_or_none()



        if pending is None:

            pending = TelegramBindingRequest(
                profile_id=profile.id,
                telegram_id=message.from_user.id,
                telegram_username=username,
                status="pending",
            )

            session.add(pending)

            await session.commit()

            request_id = pending.id

        else:
            request_id = pending.id



    await message.answer(
        f"🔒 <b>Запрос на доступ создан</b>\n\n"
        f"Профиль: <b>{profile.display_name}</b>\n"
        f"Роль: <b>{'Владелец' if profile.role == UserRole.OWNER.value else 'Администратор'}</b>\n"
        f"Telegram: @{username}\n\n"
        "Ожидается подтверждение владельца клуба."
    )


    await notify_owners(
        message.bot,
        f"🔔 <b>Новый запрос привязки Telegram</b>\n\n"
        f"Профиль: <b>{profile.display_name}</b>\n"
        f"Роль: {'👑 Владелец' if profile.role == UserRole.OWNER.value else '👤 Администратор'}\n"
        f"Telegram: @{username}\n"
        f"ID: <code>{message.from_user.id}</code>",
        review_kb(request_id),
    )


    return True



@router.message(F.text == "🔗 Заявки на привязку")
async def binding_requests(message: Message):

    async with SessionLocal() as session:

        owner = (
            await session.execute(
                select(TelegramUser).where(
                    TelegramUser.telegram_id == message.from_user.id,
                    TelegramUser.role == UserRole.OWNER.value,
                    TelegramUser.active.is_(True),
                )
            )
        ).scalar_one_or_none()


        if owner is None:
            await message.answer("⛔ Только владелец.")
            return



        rows = (
            await session.execute(
                select(
                    TelegramBindingRequest,
                    AccessProfile,
                )
                .join(
                    AccessProfile,
                    AccessProfile.id == TelegramBindingRequest.profile_id,
                )
                .where(
                    TelegramBindingRequest.status == "pending"
                )
                .order_by(
                    TelegramBindingRequest.created_at.asc()
                )
            )
        ).all()



    if not rows:
        await message.answer(
            "🔗 <b>Заявки на привязку</b>\n\n"
            "Новых заявок нет."
        )
        return



    await message.answer(
        f"🔗 <b>Заявки на привязку</b>\n\n"
        f"Новых заявок: <b>{len(rows)}</b>"
    )


    for req, profile in rows:

        await message.answer(
            f"Заявка #{req.id}\n\n"
            f"<b>{profile.display_name}</b>\n"
            f"Роль: {'👑 Владелец' if profile.role == UserRole.OWNER.value else '👤 Администратор'}\n"
            f"Telegram: @{req.telegram_username or '-'}\n"
            f"ID: <code>{req.telegram_id}</code>",
            reply_markup=review_kb(req.id),
        )



@router.callback_query(F.data.startswith("bind:approve:"))
async def approve_binding(call: CallbackQuery):

    async with SessionLocal() as session:

        owner = (
            await session.execute(
                select(TelegramUser).where(
                    TelegramUser.telegram_id == call.from_user.id,
                    TelegramUser.role == UserRole.OWNER.value,
                    TelegramUser.active.is_(True),
                )
            )
        ).scalar_one_or_none()


        if owner is None:
            await call.answer(
                "⛔ Только владелец",
                show_alert=True,
            )
            return



        rid = int(call.data.rsplit(":", 1)[1])


        req = await session.get(
            TelegramBindingRequest,
            rid,
        )


        if not req or req.status != "pending":
            await call.answer(
                "Заявка уже обработана",
                show_alert=True,
            )
            return



        profile = await session.get(
            AccessProfile,
            req.profile_id,
        )


        if not profile:
            await call.answer(
                "Профиль не найден",
                show_alert=True,
            )
            return



        user = (
            await session.execute(
                select(TelegramUser).where(
                    TelegramUser.telegram_id == req.telegram_id
                )
            )
        ).scalar_one_or_none()



        if user is None:

            user = TelegramUser(
                telegram_id=req.telegram_id,
                role=profile.role,
                employee_id=profile.employee_id,
                active=True,
            )

            session.add(user)

        else:

            user.role = profile.role
            user.employee_id = profile.employee_id
            user.active = True



        req.status = "approved"
        req.reviewed_by = call.from_user.id
        req.reviewed_at = datetime.now(timezone.utc)


        await write_audit(
            session,
            call.from_user.id,
            "telegram_binding_approved",
            "binding_request",
            str(rid),
            {
                "profile": profile.display_name,
                "telegram_id": req.telegram_id,
            },
        )
        await session.commit()


    await call.message.edit_text(
        f"✅ Привязка подтверждена: {profile.display_name}"
    )


    try:
        await call.bot.send_message(
            req.telegram_id,
            f"✅ Доступ подтверждён.\n"
            f"Профиль: {profile.display_name}",
        )
    except Exception:
        pass


    await call.answer("Готово")



@router.callback_query(F.data.startswith("bind:reject:"))
async def reject_binding(call: CallbackQuery):

    async with SessionLocal() as session:

        req_id = int(call.data.rsplit(":", 1)[1])

        req = await session.get(
            TelegramBindingRequest,
            req_id,
        )


        if not req:
            await call.answer("Не найдено")
            return


        req.status = "rejected"
        req.reviewed_by = call.from_user.id
        req.reviewed_at = datetime.now(timezone.utc)


        await session.commit()


        telegram_id = req.telegram_id



    await call.message.edit_text(
        "❌ Запрос отклонён."
    )


    try:
        await call.bot.send_message(
            telegram_id,
            "❌ Запрос на доступ отклонён владельцем клуба.",
        )
    except Exception:
        pass


    await call.answer("Отклонено")