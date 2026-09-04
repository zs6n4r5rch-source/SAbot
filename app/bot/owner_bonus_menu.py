from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Employee, UserRole
from app.services.auth import get_access

router = Router()


def bonus_list_kb(employees):
    rows = [[InlineKeyboardButton(text=f"👤 {(e.full_name or f'Администратор #{e.id}')[:38]}", callback_data=f"owner_bonus_employee:{e.id}")] for e in employees]
    rows.append([InlineKeyboardButton(text="⬅️ Панель владельца", callback_data="nav:owner")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bonus_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Все администраторы", callback_data="owner:bonuses")]])


async def owner_ok(call: CallbackQuery) -> bool:
    user = await get_access(call.message)
    return bool(user and user.active and user.role == UserRole.OWNER.value)


@router.callback_query(F.data == "owner:bonuses")
async def owner_bonuses(call: CallbackQuery):
    if not await owner_ok(call):
        await call.answer("Нет доступа", show_alert=True); return
    from app.bot.salary import _owner_bonus_dashboard
    async with SessionLocal() as session:
        employees = (await session.execute(select(Employee).where(Employee.active.is_(True)).order_by(Employee.full_name.asc()))).scalars().all()
        text = await _owner_bonus_dashboard(session)
    await call.message.edit_text(text, reply_markup=bonus_list_kb(employees))
    await call.answer()


@router.callback_query(F.data.startswith("owner_bonus_employee:"))
async def owner_bonus_employee(call: CallbackQuery):
    if not await owner_ok(call):
        await call.answer("Нет доступа", show_alert=True); return
    from app.bot.salary import _current_month_bonus_status
    eid = int(call.data.split(":", 1)[1])
    async with SessionLocal() as session:
        employee = await session.get(Employee, eid)
        if employee is None or not employee.active:
            await call.answer("Администратор не найден", show_alert=True); return
        text = await _current_month_bonus_status(eid, session)
    await call.message.edit_text(f"👤 <b>{employee.full_name or f'Администратор #{eid}'}</b>\n\n{text}", reply_markup=bonus_back_kb())
    await call.answer()
