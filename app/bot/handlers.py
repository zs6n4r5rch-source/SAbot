from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select, func

from app.bot.keyboards import (
    admin_menu,
    owner_menu,
    admins_menu,
    owner_settings_menu,
)

from app.db.session import SessionLocal

from app.models import (
    Employee,
    TelegramUser,
    UserRole,
    Shift,
    Club,
    Writeoff,
    WriteoffItem,
    WriteoffStatus,
    Discrepancy,
    SalaryPeriod,
)

from app.services.auth import (
    get_access,
)
from app.services.langame import langame_client
from app.services.staff_access import match_admin_profiles_to_employees


router = Router()

# ReplyKeyboard владельца. Telegram присылает нажатие такой кнопки
# как обычное Message с точным текстом кнопки. Чтобы порядок подключённых
# дочерних роутеров не влиял на работу меню, все кнопки OWNER маршрутизируем
# из одного обработчика основного router.
from app.bot.inline_keyboards import admin_inline_menu, owner_inline_menu

from app.bot.owner_dashboard import (
    dashboard_text,
    dashboard_keyboard,
    is_owner as owner_dashboard_is_owner,
)


OWNER_MENU_BUTTONS = {
    "📅 Ежедневная сводка",
    "👥 Администраторы",
    "🍔 Бар и снеки",
    "📊 Аналитика",
    "💰 Финансы",
    "🏆 Бонусы",
    "🔔 Требует внимания",
    "👥 Клиенты",
    "📣 Рассылки",
    "⚙️ Настройки",
}


@router.callback_query(F.data.startswith("owner:"))
async def owner_callback_dispatch(callback: CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    if not await is_owner(callback.message):
        await callback.answer("⛔ Только для владельца.", show_alert=True)
        return
    await callback.answer()
    action = callback.data.split(":", 1)[1]
    message = callback.message
    if action == "dashboard":
        await message.edit_text(await dashboard_text(), reply_markup=owner_inline_menu(settings.mini_app_url or None))
    elif action == "admins":
        await admins(message)
    elif action == "inventory":
        from app.bot.inventory import inventory_menu_handler
        await inventory_menu_handler(message)
    elif action == "analytics":
        from app.bot.analytics import analytics_menu
        await analytics_menu(message)
    elif action == "finance":
        from app.bot.finance import finance_button
        await finance_button(message)
    elif action == "bonuses":
        from app.bot.salary import owner_bonuses_view
        await owner_bonuses_view(message)
    elif action == "attention":
        from app.bot.owner_dashboard import attention_button
        await attention_button(message)
    elif action == "clients":
        from app.bot.clients import clients
        await clients(message)
    elif action == "broadcast":
        from app.bot.mailing import mailings
        await mailings(message)
    elif action == "settings":
        await settings_menu(message)
    elif action == "penalties":
        from app.bot.penalties import penalties_menu
        await penalties_menu(message)


@router.callback_query(F.data.startswith("admin:"))
async def admin_callback_dispatch(callback: CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user = await get_access(callback.message)
    if not user or user.role != UserRole.ADMIN.value:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await callback.answer()
    message = callback.message
    action = callback.data.split(":", 1)[1]
    if action == "inventory":
        from app.bot.inventory import inventory_menu_handler
        await inventory_menu_handler(message)
    elif action == "shifts":
        await my_shifts(message)
    elif action == "stats":
        await my_stats(message)
    elif action == "salary":
        from app.bot.salary import my_salary_view
        await my_salary_view(message)
    elif action == "bonuses":
        from app.bot.salary import my_bonuses_view
        await my_bonuses_view(message)
    elif action == "close_shift":
        await message.answer("🔒 Для закрытия смены используйте кнопку «🔒 Закрыть смену» в рабочем меню.")


@router.callback_query(F.data == "nav:owner")
async def owner_back_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    if not await is_owner(callback.message):
        await callback.answer("⛔ Только для владельца.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(await dashboard_text(), reply_markup=owner_inline_menu(settings.mini_app_url or None))


@router.message(F.text.in_(OWNER_MENU_BUTTONS))
async def owner_menu_dispatch(message: Message):
    if not await is_owner(message):
        await message.answer("⛔ Только для владельца.")
        return

    text = (message.text or "").strip()

    if text == "📅 Ежедневная сводка":
        await message.answer(
            await dashboard_text(),
            reply_markup=dashboard_keyboard(),
        )
        return

    if text == "👥 Администраторы":
        await admins(message)
        return

    if text == "🍔 Бар и снеки":
        from app.bot.inventory import inventory_menu_handler
        await inventory_menu_handler(message)
        return

    if text == "📊 Аналитика":
        from app.bot.analytics import analytics_menu
        await analytics_menu(message)
        return

    if text == "💰 Финансы":
        from app.bot.finance import finance_button
        await finance_button(message)
        return

    if text == "🏆 Бонусы":
        from app.bot.salary import owner_bonuses_view
        await owner_bonuses_view(message)
        return

    if text == "🔔 Требует внимания":
        from app.bot.owner_dashboard import attention_button
        await attention_button(message)
        return

    if text == "👥 Клиенты":
        from app.bot.clients import clients
        await clients(message)
        return

    if text == "📣 Рассылки":
        from app.bot.mailing import mailings
        await mailings(message)
        return

    if text == "⚙️ Настройки":
        await settings_menu(message)
        return


langame = langame_client


# подключение модулей
from app.bot.inventory import router as inventory_router
router.include_router(inventory_router)

from app.bot.salary import router as salary_router
router.include_router(salary_router)

from app.bot.guest import router as guest_router
router.include_router(guest_router)

from app.bot.admin_profiles import router as admin_profiles_router
router.include_router(admin_profiles_router)

from app.bot.integrity import router as integrity_router
router.include_router(integrity_router)

from app.bot.penalties import router as penalties_router
router.include_router(penalties_router)

from app.bot.clients import router as clients_router
router.include_router(clients_router)

from app.bot.analytics import router as analytics_router
router.include_router(analytics_router)

from app.bot.finance import router as finance_router
router.include_router(finance_router)

from app.bot.mailing import router as mailing_router
router.include_router(mailing_router)

from app.bot.admin_settings import router as admin_settings_router
router.include_router(admin_settings_router)

from app.bot.staff_binding import router as staff_binding_router
router.include_router(staff_binding_router)

from app.bot.owner_settings import router as owner_settings_router
router.include_router(owner_settings_router)

from app.bot.owner_dashboard import router as owner_dashboard_router
router.include_router(owner_dashboard_router)
