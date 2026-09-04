import secrets
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.db.session import SessionLocal
from app.services.audit import write_audit
from app.models import Guest, GuestLinkToken, GuestTelegram

router = Router()
TOKEN_TTL = timedelta(days=7)


def consent_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Согласен получать рассылки", callback_data=f"guest_consent_yes:{token}")],
        [InlineKeyboardButton(text="❌ Не хочу рассылки", callback_data=f"guest_consent_no:{token}")],
    ])


async def create_invite(message: Message, guest_langame_id: int) -> str | None:
    token = secrets.token_urlsafe(32)
    async with SessionLocal() as session:
        guest = (await session.execute(select(Guest).where(Guest.langame_guest_id == guest_langame_id))).scalar_one_or_none()
        if guest is None:
            return None
        # Old unused tokens for the same guest are invalidated by marking them used.
        rows = (await session.execute(select(GuestLinkToken).where(GuestLinkToken.guest_id == guest.id, GuestLinkToken.used_at.is_(None)))).scalars().all()
        now = datetime.now(timezone.utc)
        for row in rows:
            row.used_at = now
        session.add(GuestLinkToken(token=token, guest_id=guest.id, created_by=message.from_user.id, expires_at=now + TOKEN_TTL))
        await session.commit()
        await write_audit(session, actor_telegram_id=message.from_user.id, action="guest_invite_created", entity_type="guest", entity_id=str(guest.id), payload={"langame_guest_id": guest_langame_id, "ttl_days": 7})
    me = await message.bot.get_me()
    return f"https://t.me/{me.username}?start=guest_{token}"


async def process_invite(message: Message, token: str):
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        token_row = (await session.execute(select(GuestLinkToken).where(GuestLinkToken.token == token))).scalar_one_or_none()
        if token_row is None or token_row.used_at is not None or token_row.expires_at <= now:
            await message.answer("❌ Ссылка недействительна или истекла. Попросите владельца клуба создать новую.")
            return
        guest = await session.get(Guest, token_row.guest_id)
        if guest is None:
            await message.answer("❌ Клиент не найден. Попросите владельца клуба обновить привязку.")
            return
        existing_by_tg = (await session.execute(select(GuestTelegram).where(GuestTelegram.telegram_user_id == message.from_user.id))).scalar_one_or_none()
        if existing_by_tg and existing_by_tg.guest_id != guest.id:
            await message.answer("❌ Этот Telegram уже привязан к другому клиенту.")
            return
        existing = (await session.execute(select(GuestTelegram).where(GuestTelegram.guest_id == guest.id))).scalar_one_or_none()
        if existing and existing.telegram_user_id != message.from_user.id:
            await message.answer("❌ Этот клиент уже привязан к другому Telegram. Обратитесь к владельцу клуба.")
            return
        if existing is None:
            existing = GuestTelegram(guest_id=guest.id, telegram_user_id=message.from_user.id, telegram_chat_id=message.chat.id)
            session.add(existing)
        else:
            existing.telegram_chat_id = message.chat.id
        token_row.used_at = now
        await session.commit()
        await write_audit(session, actor_telegram_id=message.from_user.id, action="guest_telegram_linked", entity_type="guest", entity_id=str(guest.id), payload={"langame_guest_id": guest.langame_guest_id})
        name = guest.fio or f"клиент #{guest.langame_guest_id}"
    await message.answer(
        f"👋 {name}, Telegram успешно привязан к вашему профилю клуба.\n\n"
        "Хотите получать новости, акции и другие маркетинговые сообщения клуба?\n"
        "Согласие добровольное, его можно отменить командой /marketing_stop.",
        reply_markup=consent_keyboard(token),
    )


@router.message(Command("guest_invite"))
async def guest_invite(message: Message):
    # проверка владельца is intentionally local here to avoid importing handlers and creating a router cycle.
    from app.models import TelegramUser, UserRole
    async with SessionLocal() as session:
        user = (await session.execute(select(TelegramUser).where(TelegramUser.telegram_id == message.from_user.id))).scalar_one_or_none()
        if not user or not user.active or user.role != UserRole.OWNER.value:
            await message.answer("⛔ Доступ только для владельца.")
            return
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Использование: /guest_invite LANGAME_GUEST_ID")
        return
    try:
        gid = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный LANGAME guest ID.")
        return
    url = await create_invite(message, gid)
    if not url:
        await message.answer("❌ Клиент не найден в локальном кэше. Сначала найдите его через LANGAME.")
        return
    await message.answer(f"🔗 Одноразовая ссылка для клиента #{gid} (действует 7 дней):\n{url}\n\nПередайте её самому клиенту.")


@router.callback_query(F.data.startswith("guest_consent_yes:"))
async def consent_yes(callback: CallbackQuery):
    async with SessionLocal() as session:
        link = (await session.execute(select(GuestTelegram).where(GuestTelegram.telegram_user_id == callback.from_user.id))).scalar_one_or_none()
        if link is None:
            await callback.answer("Сначала откройте персональную ссылку приглашения.", show_alert=True)
            return
        link.marketing_consent = True
        link.marketing_consent_at = datetime.now(timezone.utc)
        await session.commit()
        await write_audit(session, actor_telegram_id=callback.from_user.id, action="marketing_consent_granted", entity_type="guest", entity_id=str(link.guest_id))
    await callback.message.edit_text("✅ Согласие сохранено. Вы будете получать маркетинговые сообщения клуба.\n\nОтменить: /marketing_stop")
    await callback.answer("Согласие сохранено")


@router.callback_query(F.data.startswith("guest_consent_no:"))
async def consent_no(callback: CallbackQuery):
    async with SessionLocal() as session:
        link = (await session.execute(select(GuestTelegram).where(GuestTelegram.telegram_user_id == callback.from_user.id))).scalar_one_or_none()
        if link:
            link.marketing_consent = False
            link.marketing_consent_at = None
            await session.commit()
            await write_audit(session, actor_telegram_id=callback.from_user.id, action="marketing_consent_declined", entity_type="guest", entity_id=str(link.guest_id))
    await callback.message.edit_text("❌ Маркетинговые сообщения отключены. Привязка Telegram к профилю сохранена.")
    await callback.answer("Рассылки отключены")


@router.message(Command("marketing_stop"))
async def marketing_stop(message: Message):
    async with SessionLocal() as session:
        link = (await session.execute(select(GuestTelegram).where(GuestTelegram.telegram_user_id == message.from_user.id))).scalar_one_or_none()
        if link is None:
            await message.answer("Telegram ещё не привязан к профилю клуба.")
            return
        link.marketing_consent = False
        link.marketing_consent_at = None
        await session.commit()
        await write_audit(session, actor_telegram_id=message.from_user.id, action="marketing_consent_revoked", entity_type="guest", entity_id=str(link.guest_id))
    await message.answer("🛑 Рассылки отключены. Привязка Telegram к профилю сохранена.")


@router.message(Command("marketing_status"))
async def marketing_status(message: Message):
    async with SessionLocal() as session:
        link = (await session.execute(select(GuestTelegram).where(GuestTelegram.telegram_user_id == message.from_user.id))).scalar_one_or_none()
    if link is None:
        await message.answer("Telegram ещё не привязан к профилю клуба.")
        return
    await message.answer("📣 Маркетинговые сообщения: включены." if link.marketing_consent else "📣 Маркетинговые сообщения: выключены.")
