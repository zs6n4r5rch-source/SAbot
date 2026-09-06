from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from app.models import AuditLog, InventoryOperation

from app.db.session import SessionLocal
from app.models import Employee, Shift, Club, Writeoff, WriteoffItem, WriteoffStatus, Discrepancy, SalaryPeriod, TelegramUser, UserRole
from app.bot.analytics import sales_rows

router = Router()


def period(days: int = 30):
    end = datetime.now(timezone.utc)
    return end - timedelta(days=days), end


async def is_owner(uid: int | None) -> bool:
    if uid is None:
        return False
    async with SessionLocal() as session:
        user = (await session.execute(select(TelegramUser).where(TelegramUser.telegram_id == uid))).scalar_one_or_none()
        return bool(user and user.active and user.role == UserRole.OWNER.value)


def admin_list_kb(employees):
    rows = [[InlineKeyboardButton(text=f"👤 {(e.full_name or f'Администратор #{e.id}')[:42]}", callback_data=f"aprofile:{e.id}")] for e in employees]
    rows.append([InlineKeyboardButton(text="🏆 Рейтинг", callback_data="arank:30")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_kb(eid: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 В рейтинг", callback_data=f"arank_emp:{eid}:30")],
        [InlineKeyboardButton(text="📋 Смены", callback_data=f"aprofile_shifts:{eid}:30")],
        [InlineKeyboardButton(text="📜 Аудит", callback_data=f"aprofile_audit:{eid}")],
        [InlineKeyboardButton(text="⬅️ К администраторам", callback_data="aprofiles:list")],
    ])


def shift_list_kb(rows, eid: int, days: int):
    buttons = []
    for sh, club in rows[:20]:
        status = "🟢" if sh.status == "closed" else "🟡"
        buttons.append([InlineKeyboardButton(
            text=f"{status} #{sh.langame_shift_id} · {club.name[:22]}",
            callback_data=f"aprofile_shift:{eid}:{sh.id}:{days}"
        )])
    buttons.append([InlineKeyboardButton(text="⬅️ Карточка администратора", callback_data=f"aprofile:{eid}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def profile_data(eid: int, days: int = 30):
    start, end = period(days)
    async with SessionLocal() as session:
        emp = await session.get(Employee, eid)
        if not emp:
            return None
        shifts = (await session.execute(
            select(Shift, Club).join(Club, Club.id == Shift.club_id)
            .where(Shift.employee_id == eid, Shift.started_at >= start, Shift.started_at <= end)
            .order_by(Shift.started_at.desc())
        )).all()
        writeoffs = await session.scalar(select(func.coalesce(func.sum(WriteoffItem.quantity), 0)).join(Writeoff, Writeoff.id == WriteoffItem.writeoff_id).where(
            Writeoff.employee_id == eid, Writeoff.created_at >= start, Writeoff.created_at <= end, Writeoff.status == WriteoffStatus.APPROVED.value)) or 0
        discrepancy_count = await session.scalar(select(func.count(Discrepancy.id)).where(Discrepancy.employee_id == eid, Discrepancy.created_at >= start, Discrepancy.created_at <= end)) or 0
        discrepancy_amount = await session.scalar(select(func.coalesce(func.sum(Discrepancy.quantity_difference), 0)).where(Discrepancy.employee_id == eid, Discrepancy.created_at >= start, Discrepancy.created_at <= end)) or 0
        salary = await session.scalar(select(func.coalesce(func.sum(SalaryPeriod.total_amount), 0)).where(
            SalaryPeriod.employee_id == eid, SalaryPeriod.date_from <= end.date(), SalaryPeriod.date_to >= start.date())) or 0
    shift_ids = {int(s.langame_shift_id) for s, _ in shifts}
    sales_by_shift = {}
    units_by_shift = {}
    for row in await sales_rows(start, end):
        if int(row.get("cancel", 0) or 0) == 1:
            continue
        sid = row.get("working_shift_id")
        if sid is None or int(sid) not in shift_ids:
            continue
        try:
            qty = Decimal(str(row.get("count", 0) or 0))
            amount = Decimal(str(row.get("price_sale", 0) or 0)) * qty
        except Exception:
            continue
        sales_by_shift[int(sid)] = sales_by_shift.get(int(sid), Decimal("0")) + amount
        units_by_shift[int(sid)] = units_by_shift.get(int(sid), Decimal("0")) + qty
    hours = Decimal("0")
    sales = Decimal("0")
    units = Decimal("0")
    cash_diff = Decimal("0")
    for sh, _ in shifts:
        if sh.ended_at and sh.ended_at > sh.started_at:
            hours += Decimal(str((sh.ended_at - sh.started_at).total_seconds())) / Decimal("3600")
        sales += sales_by_shift.get(int(sh.langame_shift_id), Decimal("0"))
        units += units_by_shift.get(int(sh.langame_shift_id), Decimal("0"))
        cash_diff += Decimal(str(sh.cash_difference or 0))
    return {
        "employee": emp, "shifts": shifts, "hours": hours, "sales": sales, "units": units,
        "cash_diff": cash_diff, "writeoffs": Decimal(str(writeoffs)),
        "discrepancy_count": int(discrepancy_count), "discrepancy_amount": Decimal(str(discrepancy_amount)),
        "salary": Decimal(str(salary)), "sales_by_shift": sales_by_shift, "units_by_shift": units_by_shift,
    }


async def ranking(days: int = 30):
    start, end = period(days)
    async with SessionLocal() as session:
        employees = (await session.execute(select(Employee).where(Employee.active.is_(True)).order_by(Employee.full_name.asc()))).scalars().all()
        shifts = (await session.execute(select(Shift).where(Shift.employee_id.is_not(None), Shift.started_at >= start, Shift.started_at <= end))).scalars().all()
    by_emp = {}
    for sh in shifts:
        x = by_emp.setdefault(sh.employee_id, {"hours": Decimal("0"), "shifts": 0, "cash_diff": Decimal("0")})
        x["shifts"] += 1
        x["cash_diff"] += Decimal(str(sh.cash_difference or 0))
        if sh.ended_at and sh.ended_at > sh.started_at:
            x["hours"] += Decimal(str((sh.ended_at - sh.started_at).total_seconds())) / Decimal("3600")
    shift_map = {int(s.langame_shift_id): s.employee_id for s in shifts}
    sales_by_emp = {}
    for row in await sales_rows(start, end):
        if int(row.get("cancel", 0) or 0) == 1 or row.get("working_shift_id") is None:
            continue
        eid = shift_map.get(int(row["working_shift_id"]))
        if eid is None:
            continue
        try:
            sales_by_emp[eid] = sales_by_emp.get(eid, Decimal("0")) + Decimal(str(row.get("price_sale", 0) or 0)) * Decimal(str(row.get("count", 0) or 0))
        except Exception:
            pass
    result = []
    for e in employees:
        x = by_emp.get(e.id, {"hours": Decimal("0"), "shifts": 0, "cash_diff": Decimal("0")})
        x = dict(x)
        x["sales"] = sales_by_emp.get(e.id, Decimal("0"))
        x["per_hour"] = x["sales"] / x["hours"] if x["hours"] > 0 else Decimal("0")
        result.append((e, x))
    return sorted(result, key=lambda item: (item[1]["per_hour"], item[1]["sales"]), reverse=True)


@router.message(F.text == "🏆 Рейтинг администраторов")
async def rating_button(message: Message):
    if not await is_owner(message.from_user.id if message.from_user else None):
        await message.answer("⛔ Только владелец.")
        return
    await message.answer(await ranking_text(30), reply_markup=rating_kb())


def rating_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 7 дней", callback_data="arank:7"), InlineKeyboardButton(text="📅 30 дней", callback_data="arank:30")],
        [InlineKeyboardButton(text="👥 К администраторам", callback_data="aprofiles:list")],
    ])


async def ranking_text(days: int) -> str:
    data = await ranking(days)
    if not data:
        return "🏆 <b>Рейтинг администраторов</b>\n\nНет данных за выбранный период."
    lines = [f"🏆 <b>Рейтинг администраторов — {days} дней</b>", "", "Рейтинг основан на продажах бара и снеков в пересчёте на час закрытых смен.", ""]
    for i, (e, x) in enumerate(data[:15], 1):
        risk = ""
        if x["cash_diff"] != 0:
            risk += " ⚠️"
        lines.append(f"{i}. <b>{e.full_name or f'Администратор #{e.id}'}</b>\n   {x['sales']:.2f} ₽ · {x['hours']:.1f} ч · {x['per_hour']:.2f} ₽/ч · смен {x['shifts']}{risk}")
    return "\n".join(lines)


@router.callback_query(F.data == "aprofiles:list")
async def profiles_list(call: CallbackQuery):
    if not await is_owner(call.from_user.id if call.from_user else None):
        await call.answer("Нет доступа", show_alert=True); return
    async with SessionLocal() as session:
        employees = (await session.execute(select(Employee).where(Employee.active.is_(True)).order_by(Employee.full_name.asc()))).scalars().all()
    text = "👥 <b>Администраторы</b>\n\nВыберите администратора для полной карточки."
    await call.message.edit_text(text, reply_markup=admin_list_kb(employees))
    await call.answer()
