from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Employee, TelegramUser, UserRole
from app.services.auth import get_access

router = Router()


async def _owner(call: CallbackQuery) -> bool:
    user = await get_access(call.message)
    return bool(user and user.active and user.role == UserRole.OWNER.value)


def _profile_keyboard(eid: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 В рейтинг", callback_data=f"arank_emp:{eid}:30")],
        [InlineKeyboardButton(text="📋 Смены", callback_data=f"aprofile_shifts:{eid}:30")],
        [InlineKeyboardButton(text="📜 Аудит", callback_data=f"aprofile_audit:{eid}")],
        [InlineKeyboardButton(text="🗑 Удалить администратора", callback_data=f"aprofile_delete:{eid}")],
        [InlineKeyboardButton(text="⬅️ К администраторам", callback_data="aprofiles:list")],
    ])


@router.callback_query(F.data.startswith("aprofile:"))
async def profile_with_delete(call: CallbackQuery):
    if not await _owner(call):
        await call.answer("Нет доступа", show_alert=True); return
    from app.bot.admin_profiles import profile_data
    eid = int(call.data.split(":", 1)[1])
    data = await profile_data(eid)
    if not data:
        await call.answer("Администратор не найден", show_alert=True); return
    e = data["employee"]
    text = f"👤 <b>{e.full_name or f'Администратор #{eid}'}</b>\n\nСтатус: {'🟢 активен' if e.active else '🔴 неактивен'}\nСмен за 30 дней: <b>{len(data['shifts'])}</b>\nПродажи: <b>{data['sales']:.2f} ₽</b>\nРазница по кассе: <b>{data['cash_diff']:.2f} ₽</b>\nРасхождения: <b>{data['discrepancy_count']}</b>\nСписания: <b>{data['writeoffs']:g} ед.</b>"
    await call.message.edit_text(text, reply_markup=_profile_keyboard(eid))
    await call.answer()


@router.callback_query(F.data.startswith("aprofile_delete:"))
async def profile_delete(call: CallbackQuery):
    if not await _owner(call):
        await call.answer("Нет доступа", show_alert=True); return
    eid = int(call.data.split(":", 1)[1])
    async with SessionLocal() as session:
        employee = await session.get(Employee, eid)
        if employee is None:
            await call.answer("Администратор не найден", show_alert=True); return
        links = (await session.execute(select(TelegramUser).where(TelegramUser.employee_id == eid))).scalars().all()
        if any(u.role == UserRole.OWNER.value for u in links):
            await call.answer("Владельца удалить нельзя", show_alert=True); return
        employee.active = False
        for u in links:
            u.active = False
        await session.commit()
    await call.message.edit_text(
        "🗑 <b>Администратор деактивирован.</b>\n\nИстория смен, зарплаты и нарушений сохранена. Telegram-доступ отключён.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ К администраторам", callback_data="aprofiles:list")]]),
    )
    await call.answer("Доступ отключён")
