from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Employee, GuestTelegram, MarketingCampaign, MarketingRecipient, RecipientStatus, TelegramUser, UserRole
from app.services.auth import get_access
from app.services.langame import langame_client
from app.bot.admin_profiles import admin_list_kb

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
        await call.answer("Нет доступа", show_alert=True); return
    try:
        data = await langame_client.guests_search(size=30)
        items = data.get("items") or data.get("data") or []
        if isinstance(items, dict): items = items.get("items") or items.get("data") or []
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
        await call.answer("Нет доступа", show_alert=True); return
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
