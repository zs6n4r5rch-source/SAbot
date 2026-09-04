from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Employee, UserRole
from app.services.auth import get_access

router = Router()


def bonus_list_kb(employees):
    rows = [
        [InlineKeyboardButton(
            text=(e.full_name or f"Администратор #{e.id}")[:42],
            callback_data=f"owner_bonus_employee:{e.id}",
        )]
        for e in employees
    ]
    rows.append([InlineKeyboardButton(text="↩️ Ежедневная сводка", callback_data="nav:owner")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bonus_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Все администраторы", callback_data="owner:bonuses")],
        [InlineKeyboardButton(text="↩️ Ежедневная сводка", callback_data="nav:owner")],
    ])


async def owner_ok(call: CallbackQuery) -> bool:
    if not call.from_user:
        return False
    actor = call.message.model_copy(update={"from_user": call.from_user}) if call.message else None
    user = await get_access(actor) if actor else None
    return bool(user and user.active and user.role == UserRole.OWNER.value)


@router.callback_query(F.data == "owner:bonuses")
async def owner_bonuses(call: CallbackQuery):
    if not await owner_ok(call):
        await call.answer("Нет доступа", show_alert=True)
        return
    async with SessionLocal() as session:
        employees = (await session.execute(
            select(Employee).where(Employee.active.is_(True)).order_by(Employee.full_name.asc())
        )).scalars().all()
    text = (
        "<b>Бонусы администраторов</b>\n\n"
        "Выберите администратора, чтобы открыть его персональную сводку."
    )
    if not employees:
        text += "\n\nАктивных администраторов пока нет."
    await call.message.edit_text(text, reply_markup=bonus_list_kb(employees))
    await call.answer()


@router.callback_query(F.data.startswith("owner_bonus_employee:"))
async def owner_bonus_employee(call: CallbackQuery):
    if not await owner_ok(call):
        await call.answer("Нет доступа", show_alert=True)
        return
    from app.bot.salary import _current_month_bonus_status
    try:
        eid = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Некорректный администратор", show_alert=True)
        return
    async with SessionLocal() as session:
        employee = await session.get(Employee, eid)
        if employee is None or not employee.active:
            await call.answer("Администратор не найден", show_alert=True)
            return
        text = await _current_month_bonus_status(eid, session)
    clean_name = employee.full_name or f"Администратор #{eid}"
    await call.message.edit_text(
        f"<b>{clean_name}</b>\n\n{text}",
        reply_markup=bonus_back_kb(),
    )
    await call.answer()
