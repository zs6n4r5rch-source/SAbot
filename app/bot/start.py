from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.inline_keyboards import admin_inline_menu, owner_inline_menu
from app.config import settings
from app.services.auth import get_access

router = Router()


@router.message(CommandStart())
async def start_entry(message: Message, state: FSMContext):
    """Canonical /start entry point for staff and guests."""
    await state.clear()

    args = (message.text or "").split(maxsplit=1)
    if len(args) == 2 and args[1].startswith("guest_"):
        from app.bot.guest import process_invite
        await process_invite(message, args[1][6:])
        return

    user = await get_access(message)
    if user is not None:
        if user.role == "owner":
            await message.answer(
                "👑 <b>Панель владельца</b>\n\nВыберите нужный раздел ниже или откройте Strike Arena.",
                reply_markup=owner_inline_menu(settings.mini_app_url or None),
            )
        else:
            await message.answer(
                "👤 <b>Рабочий кабинет</b>\n\nОткройте Strike Arena или выберите нужный раздел ниже.",
                reply_markup=admin_inline_menu(settings.mini_app_url or None),
            )
        return

    from app.bot.staff_binding import process_staff_start
    if await process_staff_start(message):
        return

    await message.answer("⛔ Доступ не настроен.\nОбратитесь к владельцу клуба.")
