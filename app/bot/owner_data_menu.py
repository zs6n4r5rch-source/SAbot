from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from app.config import settings
from app.db.session import SessionLocal
from app.models import Employee, GuestTelegram, MarketingCampaign, MarketingRecipient, RecipientStatus, TelegramUser, UserRole
from app.services.auth import get_access
from app.services.langame import langame_client
from app.bot.admin_profiles import admin_list_kb
from app.bot.owner_dashboard import dashboard_text
from app.bot.inline_keyboards import owner_inline_menu

router = Router()


def owner_back():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Панель владельца", callback_data="nav:owner")]])


def client_page(items):
    rows = []
    for x in items[:30]:
        gid = x.get("guest_id") or x.get("id") or "?"
        fio = x.get("fio") or x.get("name") or "Без имени"
        phone = x.get("phone") or "—"
        rows.append([InlineKeyboardButton(text=f"👤 {str(fio)[:30]} · {str(phone)[:18]}", callback_data=f"client:noop:{gid}")])
    rows.append([InlineKeyboardButton(text="⬅️ Панель владельца", callback_data="nav:owner")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def is_owner(call: CallbackQuery):
    if not call.from_user:
        return False
    async with SessionLocal() as session:
        user = (await session.execute(
            select(TelegramUser).where(TelegramUser.telegram_id == call.from_user.id)
        )).scalar_one_or_none()
    return bool(user and user.active and user.role == UserRole.OWNER.value)


async def is_owner_message(message: Message):
    user = await get_access(message)
    return bool(user and user.active and user.role == UserRole.OWNER.value)


@router.callback_query(F.data == "nav:owner")
async def owner_navigation_back(call: CallbackQuery):
    if not await is_owner(call):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.message.edit_text(
        await dashboard_text(),
        reply_markup=owner_inline_menu(settings.mini_app_url or None),
    )
    await call.answer()


@router.callback_query(F.data == "owner:admins")
async def owner_admins(call: CallbackQuery):
    if not await is_owner(call):
        await call.answer("Нет доступа", show_alert=True)
        return
    async with SessionLocal() as session:
        employees = (await session.execute(
            select(Employee)
            .where(Employee.active.is_(True))
            .order_by(Employee.full_name.asc())
        )).scalars().all()
    text = "👥 <b>Список администраторов</b>\n\nВыберите администратора для полной карточки."
    await call.message.edit_text(text, reply_markup=admin_list_kb(employees))
    await call.answer()


@router.callback_query(F.data == "owner:clients")
async def owner_clients(call: CallbackQuery):
    if not await is_owner(call):
        await call.answer("Нет доступа", show_alert=True)
        return
    try:
        data = await langame_client.guests_search(size=30)
        items = data.get("items") or data.get("data") or []
        if isinstance(items, dict):
            items = items.get("items") or items.get("data") or []
        if not items:
            text = "👥 <b>Клиенты</b>\n\nLANGAME ответил, но клиентов в первой странице нет."
        else:
            lines = [f"👥 <b>Клиенты из LANGAME</b> · {len(items)}", "", "Первые 30 клиентов:"]
            for x in items[:30]:
                lines.append(f"• <b>{x.get('fio') or x.get('name') or 'Без имени'}</b> · {x.get('phone') or 'телефон не указан'} · ID {x.get('guest_id') or x.get('id') or '—'}")
            text = "\n".join(lines)
    except Exception as exc:
        text = f"👥 <b>Клиенты</b>\n\n❌ LANGAME временно недоступен.\n{str(exc)[:300]}"
    await call.message.edit_text(text, reply_markup=owner_back())
    await call.answer()


@router.callback_query(F.data == "owner:broadcast")
async def owner_broadcast(call: CallbackQuery):
    if not await is_owner(call):
        await call.answer("Нет доступа", show_alert=True)
        return
    async with SessionLocal() as session:
        linked = await session.scalar(select(func.count(GuestTelegram.id)).where(GuestTelegram.marketing_consent.is_(True)))
        campaigns = (await session.execute(select(MarketingCampaign).order_by(MarketingCampaign.id.desc()).limit(15))).scalars().all()
        lines = ["📣 <b>Рассылки</b>", "", f"👥 Получателей с согласием: <b>{linked or 0}</b>", ""]
        if not campaigns:
            lines.append("Черновиков и отправленных кампаний пока нет.")
            lines.append("Создать рассылку можно через кнопку «➕ Новая рассылка» в Telegram-разделе рассылок.")
        else:
            lines.append("Последние кампании:")
            for c in campaigns:
                total = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == c.id))
                sent = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == c.id, MarketingRecipient.status == RecipientStatus.SENT.value))
                lines.append(f"• #{c.id} <b>{c.name}</b> — {c.status} · {sent or 0}/{total or 0}")
        text = "\n".join(lines)
    await call.message.edit_text(text, reply_markup=owner_back())
    await call.answer()


@router.callback_query(F.data == "client:noop")
async def client_noop(call: CallbackQuery):
    await call.answer("Карточка клиента будет открыта отдельным экраном.")


# Compatibility layer for the old persistent OWNER ReplyKeyboard.
# Telegram sends ReplyKeyboard presses as ordinary messages, so these
# actions must remain valid even if a client still has the old keyboard cached.
OWNER_MESSAGE_ALIASES = {
    "👑 Панель владельца": "📅 Ежедневная сводка",
    "📅 Ежедневная сводка": "📅 Ежедневная сводка",
    "👥 Администраторы": "👥 Администраторы",
    "🍔 Бар и снеки": "🍔 Бар и снеки",
    "📊 Аналитика": "📊 Аналитика",
    "💰 Финансы": "💰 Финансы",
    "🏆 Бонусы": "🏆 Бонусы",
    "🔔 Требует внимания": "🔔 Требует внимания",
    "👥 Клиенты": "👥 Клиенты",
    "📣 Рассылки": "📣 Рассылки",
    "⚙️ Настройки": "⚙️ Настройки",
}


@router.message(F.text.in_(OWNER_MESSAGE_ALIASES.keys()))
async def owner_reply_keyboard_dispatch(message: Message):
    if not await is_owner_message(message):
        await message.answer("⛔ Только для владельца.")
        return

    action = OWNER_MESSAGE_ALIASES[message.text.strip()]

    if action == "📅 Ежедневная сводка":
        await message.answer(
            await dashboard_text(),
            reply_markup=owner_inline_menu(settings.mini_app_url or None),
        )
    elif action == "👥 Администраторы":
        async with SessionLocal() as session:
            employees = (await session.execute(
                select(Employee)
                .where(Employee.active.is_(True))
                .order_by(Employee.full_name.asc())
            )).scalars().all()
        await message.answer(
            "👥 <b>Список администраторов</b>\n\nВыберите администратора для полной карточки.",
            reply_markup=admin_list_kb(employees),
        )
    elif action == "🍔 Бар и снеки":
        from app.bot.inventory import inventory_menu_handler
        await inventory_menu_handler(message)
    elif action == "📊 Аналитика":
        from app.bot.analytics import analytics_menu
        await analytics_menu(message)
    elif action == "💰 Финансы":
        from app.bot.finance import finance_button
        await finance_button(message)
    elif action == "🏆 Бонусы":
        from app.bot.salary import owner_bonuses_view
        await owner_bonuses_view(message)
    elif action == "🔔 Требует внимания":
        from app.bot.owner_dashboard import attention_button
        await attention_button(message)
    elif action == "👥 Клиенты":
        await message.answer("👥 <b>Клиенты</b>\n\nОткрываю данные LANGAME…")
        try:
            data = await langame_client.guests_search(size=30)
            items = data.get("items") or data.get("data") or []
            if isinstance(items, dict):
                items = items.get("items") or items.get("data") or []
            if not items:
                text = "LANGAME ответил, но клиентов в первой странице нет."
            else:
                lines = [f"<b>Клиенты из LANGAME</b> · {len(items)}", ""]
                for x in items[:30]:
                    lines.append(f"• <b>{x.get('fio') or x.get('name') or 'Без имени'}</b> · {x.get('phone') or '—'}")
                text = "\n".join(lines)
        except Exception as exc:
            text = f"❌ LANGAME временно недоступен.\n{str(exc)[:300]}"
        await message.answer(text, reply_markup=owner_back())
    elif action == "📣 Рассылки":
        await message.answer("📣 <b>Рассылки</b>\n\nРаздел открывается из inline-меню.", reply_markup=owner_back())
    elif action == "⚙️ Настройки":
        from app.bot.handlers import settings_menu
        await settings_menu(message)
