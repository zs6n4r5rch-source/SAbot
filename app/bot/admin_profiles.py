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
        discrepancy_amount = await session.scalar(select(func.coalesce(func.sum(Discrepancy.amount_difference), 0)).where(Discrepancy.employee_id == eid, Discrepancy.created_at >= start, Discrepancy.created_at <= end)) or 0
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


@router.callback_query(F.data.startswith("aprofile:"))
async def profile_callback(call: CallbackQuery):
    if not await is_owner(call.from_user.id if call.from_user else None):
        await call.answer("Нет доступа", show_alert=True); return
    eid = int(call.data.split(":", 1)[1])
    data = await profile_data(eid)
    if not data:
        await call.answer("Администратор не найден", show_alert=True); return
    e = data["employee"]
    status = "🟢 активен" if e.active else "🔴 неактивен"
    per_hour = data["sales"] / data["hours"] if data["hours"] > 0 else Decimal("0")
    text = (
        f"👤 <b>{e.full_name or f'Администратор #{e.id}'}</b>\n"
        f"ID: #{e.id} · LANGAME: {e.langame_user_id}\n{status}\n\n"
        f"📅 Последние 30 дней\n"
        f"📋 Смен: <b>{len(data['shifts'])}</b>\n"
        f"⏱ Часы: <b>{data['hours']:.1f}</b>\n"
        f"📈 Продажи бара и снеков: <b>{data['sales']:.2f} ₽</b> · {data['units']:g} ед.\n"
        f"📊 Продажи/час: <b>{per_hour:.2f} ₽</b>\n"
        f"💵 Разница по кассе: <b>{data['cash_diff']:.2f} ₽</b>\n"
        f"🗑 Одобренные списания: <b>{data['writeoffs']:g} ед.</b>\n"
        f"⚠️ Расхождения: <b>{data['discrepancy_count']}</b> · {data['discrepancy_amount']:.2f} ₽\n"
        f"💰 Зарплата в пересекающихся периодах: <b>{data['salary']:.2f} ₽</b>"
    )
    await call.message.edit_text(text, reply_markup=profile_kb(eid))
    await call.answer()


@router.callback_query(F.data.startswith("arank:"))
async def ranking_callback(call: CallbackQuery):
    if not await is_owner(call.from_user.id if call.from_user else None):
        await call.answer("Нет доступа", show_alert=True); return
    days = int(call.data.split(":")[1])
    await call.message.edit_text(await ranking_text(days), reply_markup=rating_kb())
    await call.answer()


@router.callback_query(F.data.startswith("arank_emp:"))
async def ranking_employee_callback(call: CallbackQuery):
    if not await is_owner(call.from_user.id if call.from_user else None):
        await call.answer("Нет доступа", show_alert=True); return
    _, eid, days = call.data.split(":")
    data = await ranking(int(days))
    pos = next((i for i, (e, _) in enumerate(data, 1) if e.id == int(eid)), None)
    text = await ranking_text(int(days))
    if pos:
        text = f"📌 Позиция администратора: <b>#{pos}</b>\n\n" + text
    await call.message.edit_text(text, reply_markup=rating_kb())
    await call.answer()


@router.callback_query(F.data.startswith("aprofile_shifts:"))
async def profile_shifts_callback(call: CallbackQuery):
    if not await is_owner(call.from_user.id if call.from_user else None):
        await call.answer("Нет доступа", show_alert=True); return
    _, eid, days = call.data.split(":")
    data = await profile_data(int(eid), int(days))
    if not data:
        await call.answer("Не найден", show_alert=True); return
    lines = [f"📋 <b>Смены — {data['employee'].full_name or f'Администратор #{eid}'}</b>", f"Последние {days} дней", "", "Нажмите на смену для подробного разбора."]
    for sh, club in data["shifts"][:20]:
        h = Decimal("0")
        if sh.ended_at and sh.ended_at > sh.started_at:
            h = Decimal(str((sh.ended_at - sh.started_at).total_seconds())) / Decimal("3600")
        amount = data["sales_by_shift"].get(int(sh.langame_shift_id), Decimal("0"))
        status = "закрыта" if sh.status == "closed" else "открыта"
        flags = []
        if sh.cash_difference not in (None, 0):
            flags.append("касса")
        if sh.status != "closed":
            flags.append("открыта")
        marker = " ⚠️" if flags else ""
        lines.append(f"• #{sh.langame_shift_id} · {club.name} · {status}{marker}\n  {sh.started_at:%d.%m %H:%M} → {(sh.ended_at.strftime('%d.%m %H:%M') if sh.ended_at else '—')} · {h:.1f} ч · бар {amount:.2f} ₽")
    await call.message.edit_text("\n".join(lines), reply_markup=shift_list_kb(data["shifts"], int(eid), int(days)))
    await call.answer()


async def shift_detail_data(local_shift_id: int):
    async with SessionLocal() as session:
        row = (await session.execute(
            select(Shift, Club, Employee).join(Club, Club.id == Shift.club_id).join(Employee, Employee.id == Shift.employee_id)
            .where(Shift.id == local_shift_id)
        )).first()
        if not row:
            return None
        sh, club, emp = row
        writeoff_rows = (await session.execute(
            select(Writeoff, WriteoffItem).join(WriteoffItem, WriteoffItem.writeoff_id == Writeoff.id)
            .where(Writeoff.shift_id == sh.id)
            .order_by(Writeoff.created_at.desc())
        )).all()
        discrepancy_rows = (await session.execute(
            select(Discrepancy).where(Discrepancy.shift_id == sh.id).order_by(Discrepancy.created_at.desc())
        )).scalars().all()
    start = sh.started_at
    end = sh.ended_at or datetime.now(timezone.utc)
    sales = Decimal("0")
    units = Decimal("0")
    sale_rows = 0
    cancel_rows = 0
    cancelled_amount = Decimal("0")
    for row in await sales_rows(start, end):
        sid = row.get("working_shift_id")
        if sid is None or int(sid) != int(sh.langame_shift_id):
            continue
        qty = Decimal(str(row.get("count", 0) or 0))
        amount = Decimal(str(row.get("price_sale", 0) or 0)) * qty
        sale_rows += 1
        if int(row.get("cancel", 0) or 0) == 1:
            cancel_rows += 1
            cancelled_amount += amount
        else:
            sales += amount
            units += qty
    approved_writeoff_units = sum((Decimal(str(i.quantity or 0)) for w, i in writeoff_rows if w.status == WriteoffStatus.APPROVED.value), Decimal("0"))
    pending_writeoff_units = sum((Decimal(str(i.quantity or 0)) for w, i in writeoff_rows if w.status == WriteoffStatus.PENDING.value), Decimal("0"))
    discrepancy_amount = sum((abs(Decimal(str(d.amount_difference or 0))) for d in discrepancy_rows), Decimal("0"))
    hours = Decimal("0")
    if sh.ended_at and sh.ended_at > sh.started_at:
        hours = Decimal(str((sh.ended_at - sh.started_at).total_seconds())) / Decimal("3600")
    cancel_rate = Decimal(cancel_rows) / Decimal(sale_rows) if sale_rows else Decimal("0")
    flags = []
    if sh.status != "closed":
        duration = (datetime.now(timezone.utc) - sh.started_at).total_seconds() / 3600
        if duration >= 16:
            flags.append("открыта более 16 часов")
        else:
            flags.append("смена ещё открыта")
    if sh.cash_difference not in (None, 0):
        flags.append(f"разница по кассе {Decimal(str(sh.cash_difference)):.2f} ₽")
    if cancel_rows >= 3:
        flags.append(f"{cancel_rows} отмен продаж")
    if cancel_rate >= Decimal("0.05") and sale_rows >= 20:
        flags.append(f"отмены {cancel_rate * 100:.1f}%")
    if approved_writeoff_units > 0:
        flags.append(f"списания {approved_writeoff_units:g} ед.")
    if discrepancy_rows:
        flags.append(f"{len(discrepancy_rows)} расхожд.")
    return {
        "shift": sh, "club": club, "employee": emp, "sales": sales, "units": units,
        "sale_rows": sale_rows, "cancel_rows": cancel_rows, "cancelled_amount": cancelled_amount,
        "cancel_rate": cancel_rate, "hours": hours, "writeoff_rows": writeoff_rows,
        "approved_writeoff_units": approved_writeoff_units, "pending_writeoff_units": pending_writeoff_units,
        "discrepancy_rows": discrepancy_rows, "discrepancy_amount": discrepancy_amount, "flags": flags,
    }


def shift_detail_kb(eid: int, days: int, shift_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔎 Расследование", callback_data=f"ashift_investigate:{eid}:{shift_id}:{days}")],
        [InlineKeyboardButton(text="📊 Сравнить с нормой", callback_data=f"ashift_baseline:{eid}:{shift_id}:{days}")],
        [InlineKeyboardButton(text="📋 Все смены", callback_data=f"aprofile_shifts:{eid}:{days}")],
        [InlineKeyboardButton(text="👤 Карточка", callback_data=f"aprofile:{eid}")],
    ])




async def shift_baseline_data(local_shift_id: int):
    """Compare one closed shift with the administrator's own historical baseline.

    Baseline uses prior closed shifts for the same employee over up to 90 days.
    We deliberately require a minimum sample before calling a metric anomalous.
    This is a review signal, not proof of misconduct.
    """
    async with SessionLocal() as session:
        current = (await session.execute(
            select(Shift, Club, Employee).join(Club, Club.id == Shift.club_id).join(Employee, Employee.id == Shift.employee_id)
            .where(Shift.id == local_shift_id)
        )).first()
        if not current:
            return None
        sh, club, emp = current
        baseline_start = sh.started_at - timedelta(days=90)
        history = (await session.execute(
            select(Shift).where(
                Shift.employee_id == sh.employee_id,
                Shift.status == "closed",
                Shift.ended_at.is_not(None),
                Shift.started_at >= baseline_start,
                Shift.started_at < sh.started_at,
            ).order_by(Shift.started_at.desc()).limit(30)
        )).scalars().all()
        writeoffs = (await session.execute(
            select(Writeoff, WriteoffItem).join(WriteoffItem, WriteoffItem.writeoff_id == Writeoff.id)
            .where(Writeoff.employee_id == sh.employee_id, Writeoff.shift_id.is_not(None),
                   Writeoff.status == WriteoffStatus.APPROVED.value, Writeoff.created_at >= baseline_start,
                   Writeoff.created_at < sh.started_at)
        )).all()
        discrepancies = (await session.execute(
            select(Discrepancy).where(Discrepancy.employee_id == sh.employee_id,
                                      Discrepancy.created_at >= baseline_start, Discrepancy.created_at < sh.started_at)
        )).scalars().all()

    async def metrics_for(shift):
        start = shift.started_at
        end = shift.ended_at or datetime.now(timezone.utc)
        sales = Decimal("0"); units = Decimal("0"); rows = 0; cancels = 0; cancelled_amount = Decimal("0")
        try:
            source_rows = await sales_rows(start, end)
        except Exception:
            source_rows = []
        for row in source_rows:
            sid = row.get("working_shift_id")
            if sid is None or int(sid) != int(shift.langame_shift_id):
                continue
            qty = Decimal(str(row.get("count", 0) or 0))
            amount = Decimal(str(row.get("price_sale", 0) or 0)) * qty
            rows += 1
            if int(row.get("cancel", 0) or 0) == 1:
                cancels += 1; cancelled_amount += amount
            else:
                sales += amount; units += qty
        hours = Decimal(str((end - start).total_seconds())) / Decimal("3600") if end > start else Decimal("0")
        return {
            "sales": sales, "units": units, "rows": rows, "cancels": cancels,
            "cancel_rate": Decimal(cancels) / Decimal(rows) if rows else Decimal("0"),
            "cancelled_amount": cancelled_amount,
            "sales_per_hour": sales / hours if hours > 0 else Decimal("0"),
            "cash_diff": abs(Decimal(str(shift.cash_difference or 0))),
        }

    current_m = await metrics_for(sh)
    hist = []
    for hs in history:
        m = await metrics_for(hs)
        async with SessionLocal() as session:
            w_units = await session.scalar(select(func.coalesce(func.sum(WriteoffItem.quantity), 0)).join(Writeoff, Writeoff.id == WriteoffItem.writeoff_id).where(Writeoff.shift_id == hs.id, Writeoff.status == WriteoffStatus.APPROVED.value)) or 0
            d_amt = await session.scalar(select(func.coalesce(func.sum(func.abs(Discrepancy.amount_difference)), 0)).where(Discrepancy.shift_id == hs.id)) or 0
        m["writeoff_units"] = Decimal(str(w_units)); m["discrepancy_amount"] = Decimal(str(d_amt))
        hist.append(m)
    current_m["writeoff_units"] = sum((Decimal(str(i.quantity or 0)) for w, i in (await _writeoffs_for_shift(sh.id))), Decimal("0"))
    current_m["discrepancy_amount"] = sum((abs(Decimal(str(d.amount_difference or 0))) for d in (await _discrepancies_for_shift(sh.id))), Decimal("0"))
    return {"shift": sh, "club": club, "employee": emp, "current": current_m, "history": hist}


async def _writeoffs_for_shift(shift_id: int):
    async with SessionLocal() as session:
        return (await session.execute(select(Writeoff, WriteoffItem).join(WriteoffItem, WriteoffItem.writeoff_id == Writeoff.id).where(Writeoff.shift_id == shift_id))).all()


async def _discrepancies_for_shift(shift_id: int):
    async with SessionLocal() as session:
        return (await session.execute(select(Discrepancy).where(Discrepancy.shift_id == shift_id))).scalars().all()


def _median(values):
    vals = sorted(values)
    if not vals:
        return None
    n = len(vals)
    if n % 2:
        return vals[n // 2]
    return (vals[n // 2 - 1] + vals[n // 2]) / Decimal("2")


def _baseline_line(label: str, value: Decimal, history_values: list[Decimal], suffix: str, higher_is_bad: bool = True):
    if len(history_values) < 5:
        return f"• {label}: {value:.2f}{suffix} · недостаточно истории (нужно ≥5 смен)"
    med = _median(history_values) or Decimal("0")
    if med <= 0:
        ratio = Decimal("0") if value <= 0 else Decimal("999")
    else:
        ratio = value / med
    flag = (ratio >= Decimal("2")) if higher_is_bad else (ratio <= Decimal("0.5"))
    marker = " ⚠️" if flag else ""
    return f"• {label}: {value:.2f}{suffix} · норма ≈ {med:.2f}{suffix} · x{ratio:.1f}{marker}"


@router.callback_query(F.data.startswith("ashift_baseline:"))
async def shift_baseline_callback(call: CallbackQuery):
    if not await is_owner(call.from_user.id if call.from_user else None):
        await call.answer("Нет доступа", show_alert=True); return
    _, eid, shift_id, days = call.data.split(":")
    data = await shift_baseline_data(int(shift_id))
    if not data or int(data["employee"].id) != int(eid):
        await call.answer("Смена не найдена", show_alert=True); return
    cur = data["current"]; hist = data["history"]
    lines = [
        f"📊 <b>Смена #{data['shift'].langame_shift_id} — сравнение с нормой</b>",
        f"👤 {data['employee'].full_name or f'Администратор #{eid}'} · {data['club'].name}",
        "",
        f"История: {len(hist)} предыдущих закрытых смен за 90 дней.",
        "⚠️ Норма — личная статистика администратора; сигнал требует проверки первичных данных.",
        "",
    ]
    lines.append(_baseline_line("Отмены, %", cur["cancel_rate"] * 100, [m["cancel_rate"] * 100 for m in hist], "%"))
    lines.append(_baseline_line("Продажи/час", cur["sales_per_hour"], [m["sales_per_hour"] for m in hist], " ₽/ч", higher_is_bad=False))
    lines.append(_baseline_line("Списания", cur["writeoff_units"], [m["writeoff_units"] for m in hist], " ед."))
    lines.append(_baseline_line("Расхождения", cur["discrepancy_amount"], [m["discrepancy_amount"] for m in hist], " ₽"))
    lines.append(_baseline_line("Разница по кассе", cur["cash_diff"], [m["cash_diff"] for m in hist], " ₽"))
    flags = []
    for label, value, vals in [
        ("отмены", cur["cancel_rate"] * 100, [m["cancel_rate"] * 100 for m in hist]),
        ("списания", cur["writeoff_units"], [m["writeoff_units"] for m in hist]),
        ("расхождения", cur["discrepancy_amount"], [m["discrepancy_amount"] for m in hist]),
        ("касса", cur["cash_diff"], [m["cash_diff"] for m in hist]),
    ]:
        if len(vals) >= 5:
            med = _median(vals) or Decimal("0")
            if (med == 0 and value > 0) or (med > 0 and value >= med * 2 and value > 0):
                flags.append(f"{label} ≥ 2× личной медианы")
    lines += ["", "🔎 <b>Итог</b>"]
    if flags:
        lines += [f"• ⚠️ {x}" for x in flags]
        if len(flags) >= 2:
            lines.append("🔴 Несколько независимых отклонений одновременно — приоритетная проверка.")
        else:
            lines.append("🟡 Есть отклонение от обычного поведения — проверить детали смены.")
    else:
        lines.append("🟢 Существенного отклонения от личной нормы не обнаружено.")
    lines += ["", "Важно: сравнение не доказывает нарушение и не учитывает внешние причины (акции, поток гостей, инциденты)."]
    await call.message.edit_text("\n".join(lines), reply_markup=shift_detail_kb(int(eid), int(days), int(shift_id)))
    await call.answer()


@router.callback_query(F.data.startswith("aprofile_shift:"))
async def profile_shift_detail_callback(call: CallbackQuery):
    if not await is_owner(call.from_user.id if call.from_user else None):
        await call.answer("Нет доступа", show_alert=True); return
    _, eid, shift_id, days = call.data.split(":")
    data = await shift_detail_data(int(shift_id))
    if not data or int(data["employee"].id) != int(eid):
        await call.answer("Смена не найдена", show_alert=True); return
    sh = data["shift"]
    status = "🟢 закрыта" if sh.status == "closed" else "🟡 открыта"
    cash = Decimal(str(sh.cash_sales or 0))
    card = Decimal(str(sh.card_sales or 0))
    mobile = Decimal(str(sh.mobile_sales or 0))
    refunds_cash = Decimal(str(sh.refunds_cash or 0))
    refunds_card = Decimal(str(sh.refunds_card or 0))
    collection = Decimal(str(sh.collection or 0))
    net_cash = cash - refunds_cash - collection
    lines = [
        f"📋 <b>Разбор смены #{sh.langame_shift_id}</b>",
        f"👤 {data['employee'].full_name or f'Администратор #{eid}'} · {data['club'].name}",
        f"{status}",
        f"🕒 {sh.started_at:%d.%m.%Y %H:%M} → {(sh.ended_at.strftime('%d.%m.%Y %H:%M') if sh.ended_at else 'ещё идёт')}",
        f"⏱ Длительность: <b>{data['hours']:.2f} ч</b>",
        "",
        "🍔 <b>Бар и снеки</b>",
        f"Продажи: <b>{data['sales']:.2f} ₽</b> · {data['units']:g} ед.",
        f"Операций продаж: {data['sale_rows']} · отмен: <b>{data['cancel_rows']}</b>",
        f"Сумма отмен: {data['cancelled_amount']:.2f} ₽ · доля {data['cancel_rate']*100:.1f}%",
        "",
        "💳 <b>Финансовые каналы LANGAME</b>",
        f"Наличные: {cash:.2f} ₽ · карта: {card:.2f} ₽ · mobile: {mobile:.2f} ₽",
        f"Возвраты: {refunds_cash + refunds_card:.2f} ₽ · инкассация: {collection:.2f} ₽",
        f"Расчётный поток наличных: {net_cash:.2f} ₽",
        "",
        f"📝 Списания: одобрено {data['approved_writeoff_units']:g} ед. · ожидает {data['pending_writeoff_units']:g} ед.",
        f"⚠️ Расхождения: {len(data['discrepancy_rows'])} · {data['discrepancy_amount']:.2f} ₽",
    ]
    if sh.handover_note:
        lines += ["", f"📌 Примечание при передаче: {sh.handover_note[:500]}"]
    if data["flags"]:
        lines += ["", "🔎 <b>Сигналы для проверки</b>"] + [f"• ⚠️ {flag}" for flag in data["flags"]]
    else:
        lines += ["", "🟢 Явных сигналов по этой смене не найдено."]
    await call.message.edit_text("\n".join(lines), reply_markup=shift_detail_kb(int(eid), int(days), int(shift_id)))
    await call.answer()




async def shift_investigation_data(local_shift_id: int):
    """Build a factual, chronological investigation view for one shift.

    LANGAME remains read-only. Sales are read from LANGAME and local actions
    (writeoffs, discrepancies, inventory operations and audit records) are
    read from our immutable/local logs. The result is a review aid, not a
    verdict about an employee.
    """
    async with SessionLocal() as session:
        row = (await session.execute(
            select(Shift, Club, Employee).join(Club, Club.id == Shift.club_id).join(Employee, Employee.id == Shift.employee_id)
            .where(Shift.id == local_shift_id)
        )).first()
        if not row:
            return None
        sh, club, emp = row
        writeoffs = (await session.execute(
            select(Writeoff, WriteoffItem).join(WriteoffItem, WriteoffItem.writeoff_id == Writeoff.id)
            .where(Writeoff.shift_id == sh.id).order_by(Writeoff.created_at.asc())
        )).all()
        discrepancies = (await session.execute(
            select(Discrepancy).where(Discrepancy.shift_id == sh.id).order_by(Discrepancy.created_at.asc())
        )).scalars().all()
        inv_ops = (await session.execute(
            select(InventoryOperation).where(InventoryOperation.shift_id == sh.id)
            .order_by(InventoryOperation.created_at.asc())
        )).scalars().all()
        audits = (await session.execute(
            select(AuditLog).where(
                AuditLog.actor_employee_id == emp.id,
                AuditLog.created_at >= sh.started_at,
                AuditLog.created_at <= (sh.ended_at or datetime.now(timezone.utc)),
            ).order_by(AuditLog.created_at.asc())
        )).scalars().all()

    events = []
    for w, item in writeoffs:
        events.append((w.created_at, "writeoff", f"списание #{w.id}: {item.quantity:g} ед. · {w.status}"))
    for d in discrepancies:
        events.append((d.created_at, "discrepancy", f"расхождение #{d.id}: {Decimal(str(d.quantity_difference or 0)):g} ед. · {Decimal(str(d.amount_difference or 0)):.2f} ₽ · {d.status}"))
    for op in inv_ops:
        events.append((op.created_at, "inventory", f"операция остатков #{op.id}: {op.operation_type} · {Decimal(str(op.quantity or 0)):g} ед."))
    for a in audits:
        events.append((a.created_at, "audit", f"аудит: {a.action}"))

    # Sales chronology. LANGAME sales have their own `date` field; aggregate
    # by minute to avoid flooding Telegram with one line per item.
    sales_by_time = {}
    try:
        for row in await sales_rows(sh.started_at, sh.ended_at or datetime.now(timezone.utc)):
            if row.get("working_shift_id") is None or int(row["working_shift_id"]) != int(sh.langame_shift_id):
                continue
            raw_date = row.get("date")
            if raw_date is None:
                continue
            if isinstance(raw_date, str):
                try:
                    dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                except Exception:
                    continue
            else:
                dt = raw_date
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.replace(second=0, microsecond=0)
            qty = Decimal(str(row.get("count", 0) or 0))
            amount = Decimal(str(row.get("price_sale", 0) or 0)) * qty
            cancelled = int(row.get("cancel", 0) or 0) == 1
            key = (dt, cancelled)
            cur = sales_by_time.get(key, [0, Decimal("0")])
            cur[0] += 1
            cur[1] += amount
            sales_by_time[key] = cur
        for (dt, cancelled), (count, amount) in sales_by_time.items():
            label = "отмены продаж" if cancelled else "продажи"
            events.append((dt, "sale", f"{label}: {count} операций · {amount:.2f} ₽"))
    except Exception:
        pass

    events.sort(key=lambda x: x[0])
    return {"shift": sh, "club": club, "employee": emp, "events": events,
            "writeoffs": writeoffs, "discrepancies": discrepancies, "inv_ops": inv_ops}


@router.callback_query(F.data.startswith("ashift_investigate:"))
async def shift_investigation_callback(call: CallbackQuery):
    if not await is_owner(call.from_user.id if call.from_user else None):
        await call.answer("Нет доступа", show_alert=True); return
    _, eid, shift_id, days = call.data.split(":")
    data = await shift_investigation_data(int(shift_id))
    if not data or int(data["employee"].id) != int(eid):
        await call.answer("Смена не найдена", show_alert=True); return

    sh, club, emp = data["shift"], data["club"], data["employee"]
    start = sh.started_at
    end = sh.ended_at or datetime.now(timezone.utc)
    duration_h = (end - start).total_seconds() / 3600
    sales = [e for e in data["events"] if e[1] == "sale"]
    cancels = [e for e in sales if "отмены" in e[2]]
    local_flags = []
    if len(cancels) >= 3:
        local_flags.append(f"много отмен продаж: {sum(int(e[2].split(': ')[1].split()[0]) for e in cancels)}")
    if data["writeoffs"]:
        approved = sum(Decimal(str(i.quantity or 0)) for w, i in data["writeoffs"] if w.status == WriteoffStatus.APPROVED.value)
        if approved > 0:
            local_flags.append(f"одобренные списания: {approved:g} ед.")
    if data["discrepancies"]:
        local_flags.append(f"расхождения: {len(data['discrepancies'])}")
    if sh.cash_difference not in (None, 0):
        local_flags.append(f"разница по кассе: {Decimal(str(sh.cash_difference)):.2f} ₽")

    lines = [
        f"🔎 <b>Расследование смены #{sh.langame_shift_id}</b>",
        f"👤 {emp.full_name or f'Администратор #{eid}'} · {club.name}",
        f"🕒 {start:%d.%m.%Y %H:%M} → {(sh.ended_at.strftime('%d.%m.%Y %H:%M') if sh.ended_at else 'ещё идёт')}",
        f"⏱ {duration_h:.2f} ч",
        "",
        "⚠️ <b>Что требует проверки</b>" if local_flags else "🟢 <b>Явных локальных сигналов нет</b>",
    ]
    lines += [f"• {x}" for x in local_flags[:6]]
    lines += ["", "🧭 <b>Хронология</b>"]
    if not data["events"]:
        lines.append("Нет зафиксированных событий внутри смены.")
    else:
        for dt, kind, text in data["events"][-25:]:
            icon = {"sale": "🍔", "writeoff": "📝", "discrepancy": "⚠️", "inventory": "📦", "audit": "📜"}.get(kind, "•")
            lines.append(f"{dt:%H:%M} {icon} {text[:150]}")
    lines += ["", "ℹ️ Данные показывают факты и аномалии для проверки, но не доказывают нарушение."]
    await call.message.edit_text("\n".join(lines), reply_markup=shift_detail_kb(int(eid), int(days), int(shift_id)))
    await call.answer()

@router.callback_query(F.data.startswith("aprofile_audit:"))
async def profile_audit_callback(call: CallbackQuery):
    if not await is_owner(call.from_user.id if call.from_user else None):
        await call.answer("Нет доступа", show_alert=True); return
    eid = int(call.data.split(":")[1])
    from app.models import AuditLog
    async with SessionLocal() as session:
        rows = (await session.execute(select(AuditLog).where(AuditLog.entity_type == "employee", AuditLog.entity_id == str(eid)).order_by(AuditLog.created_at.desc()).limit(15))).scalars().all()
    text = "📜 <b>Аудит администратора</b>\n\n" + ("\n".join(f"{r.created_at:%d.%m %H:%M} · {r.action}" for r in rows) if rows else "Записей нет.")
    await call.message.edit_text(text, reply_markup=profile_kb(eid))
    await call.answer()
