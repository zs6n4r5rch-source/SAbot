from __future__ import annotations

from datetime import date, datetime, time, timezone, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_HALF_UP

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, delete, func

from app.db.session import SessionLocal
from app.models import Employee, Club, Shift, SalaryRule, SalaryPeriod, SalaryAdjustment, SalaryPayment, UserRole, ShiftCloseReport, ShiftCloseStockItem, NonMonetaryBonus, SalaryViolation
from app.services.auth import get_access
from app.services.langame import LangameClient, langame_client
from app.services.audit import write_audit

router = Router()
langame = langame_client


class SalaryUIState(StatesGroup):
    waiting_period = State()
    waiting_adjustment = State()
    waiting_review_bonus = State()


def salary_keyboard(period_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Премия", callback_data=f"salary_adj:{period_id}:plus"),
         InlineKeyboardButton(text="➖ Вычет", callback_data=f"salary_adj:{period_id}:minus")],
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"salary_confirm:{period_id}"),
         InlineKeyboardButton(text="💸 Выплатить", callback_data=f"salary_pay:{period_id}")],
    ])


def salary_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Синхронизировать смены", callback_data="salary_sync")],
        [InlineKeyboardButton(text="📅 Новый расчёт", callback_data="salary_period_ui")],
        [InlineKeyboardButton(text="👥 Администраторы", callback_data="salary_employees")],
        [InlineKeyboardButton(text="⭐ Бонус за отзыв", callback_data="salary_review_bonus_ui")],
    ])


def format_period(period: SalaryPeriod, employee: Employee, hours: Decimal, rate: Decimal) -> str:
    return (f"💰 {employee.full_name or employee.langame_user_id}\n"
            f"Период: {period.date_from} — {period.date_to}\n"
            f"Смен: {getattr(period, '_shift_count', 0)}\n"
            f"Часов: {hours.quantize(Decimal('0.01'))}\n"
            f"Оплата за смену: {rate} ₽\n"
            f"База: {period.base_amount} ₽\n"
            f"Премии и корректировки: {period.bonus_amount} ₽\n"
            f"Штрафы: {getattr(period, '_penalty_total', Decimal('0.00'))} ₽\n"
            f"Итого: {period.total_amount} ₽\n"
            f"Статус: {period.status}")

MONEY = Decimal("0.01")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


async def owner_only(message: Message):
    user = await get_access(message)
    if user is None or user.role != UserRole.OWNER.value:
        await message.answer("⛔ Только владелец.")
        return None
    return user


async def sync_shifts_data() -> tuple[int, int, int]:
    page = 1
    created = updated = skipped = 0
    while True:
        result = await langame.shifts(page=page, page_limit=100)
        items = result.get("data") or []
        if not items:
            break
        async with SessionLocal() as session:
            clubs_result = await session.execute(select(Club))
            clubs = {c.langame_club_id: c for c in clubs_result.scalars().all()}
            employees_result = await session.execute(select(Employee))
            employees = {e.langame_user_id: e for e in employees_result.scalars().all()}
            for item in items:
                sid = item.get("id")
                club = clubs.get(item.get("list_clubs_id"))
                employee = employees.get(item.get("user_id"))
                started = parse_dt(item.get("date_start"))
                ended = parse_dt(item.get("date_stop"))
                if sid is None or club is None or started is None:
                    skipped += 1
                    continue
                q = await session.execute(select(Shift).where(Shift.langame_shift_id == int(sid)))
                shift = q.scalar_one_or_none()
                if shift is None:
                    shift = Shift(langame_shift_id=int(sid), club_id=club.id, employee_id=employee.id if employee else None, started_at=started)
                    session.add(shift)
                    created += 1
                else:
                    updated += 1
                    shift.club_id = club.id
                    shift.employee_id = employee.id if employee else None
                    shift.started_at = started
                shift.ended_at = ended
                shift.status = "closed" if ended else "open"
                # Financial fields are read-only snapshots from LANGAME.
                # We keep payment channels separately so Owner analytics can
                # show cash/card/mobile/refunds/collection without inventing
                # an "actual cash" value.
                shift.cash_sales = Decimal(str(item.get("nal", 0) or 0))
                shift.card_sales = Decimal(str(item.get("beznal", 0) or 0))
                shift.mobile_sales = Decimal(str(item.get("mobile_pay", 0) or 0)) + Decimal(str(item.get("yandex_pay", 0) or 0))
                shift.refunds_cash = Decimal(str(item.get("refunds_nal", 0) or 0))
                shift.refunds_card = Decimal(str(item.get("refunds_beznal", 0) or 0))
                shift.collection = Decimal(str(item.get("incass", 0) or 0))
                # Actual cash and cash difference are entered by the administrator
                # in the mandatory shift-close report. Never erase them on sync.
                shift.system_cash = shift.cash_sales
                shift.handover_note = item.get("message")
            await session.commit()
        total_pages = result.get("total_pages")
        if not total_pages or page >= int(total_pages):
            break
        page += 1
    return created, updated, skipped


SHIFT_PAY = Decimal("2000.00")


async def active_hourly_rate(session) -> Decimal:
    """Fixed base pay per closed shift. Kept under the old helper name for compatibility."""
    return SHIFT_PAY


CLEANING_MONTHLY_BONUS = Decimal("500.00")
IDEAL_CLOSE_MONTHLY_BONUS = Decimal("250.00")
CASH_DISCIPLINE_MONTHLY_BONUS = Decimal("250.00")
BAR_THRESHOLD = Decimal("30000.00")
BAR_BASE_RATE = Decimal("0.05")
BAR_EXCESS_RATE = Decimal("0.05")
BAR_TOP_RATE = Decimal("0.05")
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _is_night_shift(shift: Shift) -> bool:
    if not shift.started_at or not shift.ended_at or shift.ended_at <= shift.started_at:
        return False
    start = shift.started_at.astimezone(MOSCOW_TZ)
    end = shift.ended_at.astimezone(MOSCOW_TZ)
    return start.date() < end.date()


def _utc_bounds_for_moscow_month(year: int, month: int) -> tuple[datetime, datetime]:
    local_start = datetime(year, month, 1, tzinfo=MOSCOW_TZ)
    if month == 12:
        local_end = datetime(year + 1, 1, 1, tzinfo=MOSCOW_TZ)
    else:
        local_end = datetime(year, month + 1, 1, tzinfo=MOSCOW_TZ)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def _is_full_calendar_month(date_from: date, date_to: date) -> bool:
    if date_from.day != 1:
        return False
    next_month = date(date_from.year + (1 if date_from.month == 12 else 0), 1 if date_from.month == 12 else date_from.month + 1, 1)
    return date_to == next_month - timedelta(days=1)


async def monthly_cleaning_bonus(employee_id: int, date_from: date, date_to: date, session) -> Decimal:
    """One 500 ₽ bonus for a completed calendar month with no missed scheduled cleanings.

    Cleaning is scheduled every second night shift in each club and is not assigned
    to a particular administrator. The administrator's shift-close report only
    records that the scheduled cleaning was completed and who performed it.
    """
    if not _is_full_calendar_month(date_from, date_to):
        return Decimal("0.00")
    today_moscow = datetime.now(MOSCOW_TZ).date()
    if date_to >= today_moscow:
        return Decimal("0.00")
    month_start_utc, month_end_utc = _utc_bounds_for_moscow_month(date_from.year, date_from.month)
    result = await session.execute(select(Shift).where(
        Shift.employee_id == employee_id, Shift.status == "closed",
        Shift.started_at >= month_start_utc, Shift.started_at < month_end_utc,
    ))
    admin_night_shifts = [shift for shift in result.scalars().all() if _is_night_shift(shift)]
    night_shifts = admin_night_shifts
    if not night_shifts:
        return Decimal("0.00")
    # Only scheduled cleaning shifts are relevant; because the duty is shared by
    # the club, the absence of a particular administrator from a cleaning slot is
    # not itself a violation. We award this bonus when every scheduled cleaning
    # slot in clubs where the administrator worked at night has a performer recorded.
    club_ids = {s.club_id for s in admin_night_shifts}
    all_night_result = await session.execute(select(Shift).where(
        Shift.club_id.in_(club_ids), Shift.status == "closed",
        Shift.started_at >= month_start_utc, Shift.started_at < month_end_utc,
    ).order_by(Shift.club_id.asc(), Shift.started_at.asc()))
    by_club: dict[int, list[Shift]] = {}
    for shift in all_night_result.scalars().all():
        if _is_night_shift(shift):
            by_club.setdefault(shift.club_id, []).append(shift)
    scheduled_ids = []
    for shifts in by_club.values():
        scheduled_ids.extend(s.id for idx, s in enumerate(shifts, start=1) if idx % 2 == 0)
    if not scheduled_ids:
        return Decimal("0.00")
    reports = (await session.execute(select(ShiftCloseReport).where(ShiftCloseReport.shift_id.in_(scheduled_ids)))).scalars().all()
    report_map = {r.shift_id: r for r in reports}
    if any(report_map.get(sid) is None or report_map[sid].cleaning_confirmed_at is None or not report_map[sid].cleaning_performed_by for sid in scheduled_ids):
        return Decimal("0.00")
    return CLEANING_MONTHLY_BONUS


async def monthly_shift_close_bonuses(employee_id: int, date_from: date, date_to: date, session) -> tuple[Decimal, Decimal]:
    """Return (ideal-close, cash-discipline) bonuses for a completed calendar month."""
    if not _is_full_calendar_month(date_from, date_to) or date_to >= datetime.now(MOSCOW_TZ).date():
        return Decimal("0.00"), Decimal("0.00")
    start = datetime.combine(date_from, time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
    shifts = (await session.execute(select(Shift).where(
        Shift.employee_id == employee_id, Shift.status == "closed",
        Shift.started_at >= start, Shift.started_at < end,
    ))).scalars().all()
    if not shifts:
        return Decimal("0.00"), Decimal("0.00")
    reports = (await session.execute(select(ShiftCloseReport).where(ShiftCloseReport.shift_id.in_([s.id for s in shifts])))).scalars().all()
    report_map = {r.shift_id: r for r in reports}
    if len(report_map) != len(shifts):
        return Decimal("0.00"), Decimal("0.00")
    cash_ok = all(r.status == "submitted" and r.cash_difference is not None and Decimal(r.cash_difference) >= 0 for r in reports)
    shift_by_id = {s.id: s for s in shifts}
    # Cleaning is required only on every second night shift in the club, not on every night shift.
    # Determine scheduled slots consistently with the shift-close workflow.
    scheduled_cleaning_ids: set[int] = set()
    club_ids = {s.club_id for s in shifts if _is_night_shift(s)}
    if club_ids:
        all_night_result = await session.execute(select(Shift).where(
            Shift.club_id.in_(club_ids), Shift.status == "closed",
            Shift.started_at >= start, Shift.started_at < end,
        ).order_by(Shift.club_id.asc(), Shift.started_at.asc()))
        by_club: dict[int, list[Shift]] = {}
        for s in all_night_result.scalars().all():
            if _is_night_shift(s):
                by_club.setdefault(s.club_id, []).append(s)
        for club_shifts in by_club.values():
            scheduled_cleaning_ids.update(s.id for idx, s in enumerate(club_shifts, start=1) if idx % 2 == 0)
    ideal_ok = cash_ok and all(
        r.status == "submitted" and (r.stock_discrepancies_count or 0) == 0 and
        (r.shift_id not in scheduled_cleaning_ids or r.cleaning_confirmed_at is not None)
        for r in reports
    )
    return (IDEAL_CLOSE_MONTHLY_BONUS if ideal_ok else Decimal("0.00"),
            CASH_DISCIPLINE_MONTHLY_BONUS if cash_ok else Decimal("0.00"))


async def monthly_bar_bonus(employee_id: int, date_from: date, date_to: date, session) -> Decimal:
    """5% at 30k + 5% of excess + extra 5% for the calendar-month top seller."""
    if not _is_full_calendar_month(date_from, date_to) or date_to >= datetime.now(MOSCOW_TZ).date():
        return Decimal("0.00")
    start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
    shifts = (await session.execute(select(Shift).where(
        Shift.employee_id.is_not(None), Shift.status == "closed",
        Shift.started_at >= start, Shift.started_at < end,
    ))).scalars().all()
    if not shifts:
        return Decimal("0.00")
    cache_key = (date_from, date_to)
    cache = session.info.setdefault("monthly_bar_sales", {})
    totals = cache.get(cache_key)
    if totals is None:
        by_langame_shift = {int(s.langame_shift_id): s for s in shifts}
        totals = {}
        page = 1
        while True:
            result = await langame.product_sales(date_from.isoformat(), date_to.isoformat(), page=page, page_limit=100)
            rows = result.get("data") or result.get("items") or []
            if not rows:
                break
            for row in rows:
                if int(row.get("cancel", 0) or 0) == 1:
                    continue
                sid = row.get("working_shift_id")
                shift = by_langame_shift.get(int(sid)) if sid is not None else None
                if shift is None or shift.employee_id is None:
                    continue
                try:
                    totals[shift.employee_id] = totals.get(shift.employee_id, Decimal("0.00")) + Decimal(str(row.get("price_sale", 0) or 0)) * Decimal(str(row.get("count", 0) or 0))
                except Exception:
                    continue
            total_pages = result.get("total_pages")
            if not total_pages or page >= int(total_pages):
                break
            page += 1
        cache[cache_key] = totals
    sales = totals.get(employee_id, Decimal("0.00"))
    if sales < BAR_THRESHOLD:
        return Decimal("0.00")
    bonus = (BAR_THRESHOLD * BAR_BASE_RATE) + ((sales - BAR_THRESHOLD) * BAR_EXCESS_RATE)
    top_employee_id = max(totals, key=lambda eid: (totals[eid], -eid)) if totals else None
    if top_employee_id == employee_id:
        bonus += sales * BAR_TOP_RATE
    return bonus.quantize(MONEY, rounding=ROUND_HALF_UP)


async def calculate_period(employee_id: int, date_from: date, date_to: date, rate: Decimal, session) -> SalaryPeriod:
    result = await session.execute(select(SalaryPeriod).where(
        SalaryPeriod.employee_id == employee_id,
        SalaryPeriod.date_from == date_from,
        SalaryPeriod.date_to == date_to,
    ))
    period = result.scalar_one_or_none()
    if period is None:
        period = SalaryPeriod(employee_id=employee_id, date_from=date_from, date_to=date_to)
        session.add(period)
        await session.flush()

    shifts_result = await session.execute(select(Shift).where(
        Shift.employee_id == employee_id,
        Shift.status == "closed",
        Shift.started_at >= datetime.combine(date_from, time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc),
        Shift.started_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc),
    ))
    shifts = shifts_result.scalars().all()
    hours = Decimal("0")
    for shift in shifts:
        if shift.ended_at and shift.ended_at > shift.started_at:
            hours += Decimal(str((shift.ended_at - shift.started_at).total_seconds())) / Decimal("3600")
    # Base salary is fixed: 2,000 ₽ for every closed shift.
    base = (Decimal(len(shifts)) * rate).quantize(MONEY, rounding=ROUND_HALF_UP)

    adj_result = await session.execute(select(SalaryAdjustment).where(SalaryAdjustment.salary_period_id == period.id))
    adjustments = adj_result.scalars().all()
    adjustment_total = sum((Decimal(a.amount) for a in adjustments), Decimal("0"))
    cleaning_bonus_total = await monthly_cleaning_bonus(employee_id, date_from, date_to, session)
    ideal_close_bonus, cash_discipline_bonus = await monthly_shift_close_bonuses(employee_id, date_from, date_to, session)
    bar_bonus = await monthly_bar_bonus(employee_id, date_from, date_to, session)
    violations = (await session.execute(select(SalaryViolation).where(
        SalaryViolation.employee_id == employee_id,
        SalaryViolation.created_at >= datetime.combine(date_from, time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc),
        SalaryViolation.created_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc),
    ))).scalars().all()
    fixed_penalties = sum((Decimal(v.amount or 0) for v in violations), Decimal("0"))
    premium_reduction = any(Decimal(v.premium_reduction_percent or 0) >= 100 for v in violations)
    period._penalty_total = fixed_penalties.quantize(MONEY, rounding=ROUND_HALF_UP)
    positive_bonuses = max(Decimal("0"), adjustment_total) + cleaning_bonus_total + ideal_close_bonus + cash_discipline_bonus + bar_bonus
    if premium_reduction:
        positive_bonuses = Decimal("0")
    negative_adjustments = min(Decimal("0"), adjustment_total)
    bonus_total = positive_bonuses + negative_adjustments - fixed_penalties
    period.base_amount = base
    period.bonus_amount = bonus_total.quantize(MONEY, rounding=ROUND_HALF_UP)
    period.total_amount = (base + bonus_total).quantize(MONEY, rounding=ROUND_HALF_UP)
    return period


@router.message(Command("sync_shifts"))
async def sync_shifts(message: Message):
    if not await owner_only(message):
        return
    try:
        created, updated, skipped = await sync_shifts_data()
        await message.answer(f"✅ Смены синхронизированы из LANGAME.\nНовых: {created}\nОбновлено: {updated}\nПропущено: {skipped}")
    except Exception as exc:
        await message.answer(f"❌ Ошибка синхронизации смен: {str(exc)[:300]}")


@router.message(Command("salary_period"))
async def salary_period(message: Message):
    if not await owner_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer("Использование: /salary_period 2026-09-01 2026-09-30")
        return
    try:
        date_from, date_to = parse_date(parts[1]), parse_date(parts[2])
        if date_to < date_from:
            raise ValueError
    except ValueError:
        await message.answer("❌ Неверный период. Используйте YYYY-MM-DD.")
        return
    async with SessionLocal() as session:
        rate = await active_hourly_rate(session)
        if rate is None:
            await message.answer("❌ Не удалось определить фиксированную оплату за смену.")
            return
        employees_result = await session.execute(select(Employee).where(Employee.active.is_(True)).order_by(Employee.full_name.asc()))
        employees = employees_result.scalars().all()
        if not employees:
            await message.answer("Нет активных администраторов.")
            return
        lines = [f"💰 Зарплата за {date_from} — {date_to}", f"Оплата: {rate} ₽ за смену", ""]
        for employee in employees:
            period = await calculate_period(employee.id, date_from, date_to, rate, session)
            lines.append(f"#{employee.id} {employee.full_name or employee.langame_user_id}: {period.total_amount} ₽")
        await session.commit()
    await message.answer("\n".join(lines))


@router.message(Command("salary"))
async def salary_command(message: Message):
    user = await owner_only(message)
    if user is None:
        return
    parts = (message.text or "").split()
    if len(parts) != 4:
        await message.answer("Использование: /salary EMPLOYEE_ID 2026-09-01 2026-09-30")
        return
    try:
        employee_id = int(parts[1])
        date_from, date_to = parse_date(parts[2]), parse_date(parts[3])
    except ValueError:
        await message.answer("❌ Неверные параметры.")
        return
    async with SessionLocal() as session:
        employee_result = await session.execute(select(Employee).where(Employee.id == employee_id))
        employee = employee_result.scalar_one_or_none()
        rate = await active_hourly_rate(session)
        if employee is None or rate is None:
            await message.answer("❌ Сотрудник не найден.")
            return
        period = await calculate_period(employee.id, date_from, date_to, rate, session)
        shifts_result = await session.execute(select(Shift).where(
            Shift.employee_id == employee.id, Shift.status == "closed",
            Shift.started_at >= datetime.combine(date_from, time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc),
            Shift.started_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc),
        ))
        shifts = shifts_result.scalars().all()
        hours = sum((Decimal(str((s.ended_at - s.started_at).total_seconds())) / Decimal("3600") for s in shifts if s.ended_at), Decimal("0"))
        await session.commit()
    await message.answer(
        f"💰 {employee.full_name or employee.langame_user_id}\n"
        f"Период: {date_from} — {date_to}\n"
        f"Смен: {len(shifts)}\nЧасов: {hours.quantize(Decimal('0.01'))}\n"
        f"Оплата: {rate} ₽ за смену\nБаза: {period.base_amount} ₽\n"
        f"Корректировки: {period.bonus_amount} ₽\nИтого: {period.total_amount} ₽\n"
        f"Статус: {period.status}"
    )


@router.message(Command("confirm_salary"))
async def confirm_salary(message: Message):
    user = await owner_only(message)
    if user is None:
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /confirm_salary PERIOD_ID")
        return
    period_id = int(parts[1])
    async with SessionLocal() as session:
        result = await session.execute(select(SalaryPeriod).where(SalaryPeriod.id == period_id))
        period = result.scalar_one_or_none()
        if period is None:
            await message.answer("❌ Период не найден.")
            return
        if period.status == "paid":
            await message.answer("Период уже выплачен.")
            return
        period.status = "confirmed"
        period.confirmed_by = message.from_user.id
        period.confirmed_at = datetime.now(timezone.utc)
        await write_audit(session, actor_telegram_id=message.from_user.id, action="salary_period_confirmed", entity_type="salary_period", entity_id=str(period.id), payload={"total": str(period.total_amount)})
        await session.commit()
    await message.answer(f"✅ Период #{period_id} подтверждён: {period.total_amount} ₽.")


@router.message(Command("pay_salary"))
async def pay_salary(message: Message):
    user = await owner_only(message)
    if user is None:
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: /pay_salary PERIOD_ID [комментарий]")
        return
    period_id = int(parts[1])
    comment = parts[2] if len(parts) == 3 else None
    async with SessionLocal() as session:
        result = await session.execute(select(SalaryPeriod).where(SalaryPeriod.id == period_id))
        period = result.scalar_one_or_none()
        if period is None:
            await message.answer("❌ Период не найден.")
            return
        if period.status != "confirmed":
            await message.answer("❌ Выплату можно провести только после подтверждения владельца.")
            return
        existing = await session.execute(select(SalaryPayment).where(SalaryPayment.salary_period_id == period.id))
        if existing.scalar_one_or_none():
            await message.answer("❌ Выплата уже зарегистрирована.")
            return
        session.add(SalaryPayment(salary_period_id=period.id, amount=period.total_amount, paid_by=message.from_user.id, comment=comment))
        period.status = "paid"
        await write_audit(session, actor_telegram_id=message.from_user.id, action="salary_paid", entity_type="salary_period", entity_id=str(period.id), payload={"amount": str(period.total_amount)})
        await session.commit()
    await message.answer(f"✅ Выплата по периоду #{period_id} зарегистрирована: {period.total_amount} ₽.")



async def _current_month_bonus_status(employee_id: int, session) -> str:
    """Show earned/currently satisfied bonuses separately from conditional ones."""
    today = datetime.now(MOSCOW_TZ).date()
    month_start = today.replace(day=1)
    start = datetime.combine(month_start, time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
    shifts = (await session.execute(select(Shift).where(Shift.employee_id == employee_id, Shift.status == "closed", Shift.started_at >= start, Shift.started_at < end))).scalars().all()
    reports = (await session.execute(select(ShiftCloseReport).where(ShiftCloseReport.shift_id.in_([s.id for s in shifts])))).scalars().all() if shifts else []
    report_map = {r.shift_id: r for r in reports}
    lines = ["🏆 МОИ БОНУСЫ", f"Период: {month_start} — {today}", ""]
    earned, conditional = [], []
    period_q = await session.execute(select(SalaryPeriod).where(SalaryPeriod.employee_id == employee_id, SalaryPeriod.date_from == month_start, SalaryPeriod.date_to == today))
    period = period_q.scalar_one_or_none()
    if period is not None:
        adjustments = (await session.execute(select(SalaryAdjustment).where(SalaryAdjustment.salary_period_id == period.id, SalaryAdjustment.amount > 0))).scalars().all()
        manual_plus = sum((Decimal(a.amount) for a in adjustments), Decimal("0"))
        if manual_plus > 0: earned.append(f"🎁 Дополнительная премия: +{manual_plus.quantize(MONEY)} ₽")
    cash_ok = bool(shifts) and len(report_map) == len(shifts) and all(r.status == "submitted" and r.cash_difference is not None and Decimal(r.cash_difference) >= 0 for r in reports)
    ideal_ok = bool(shifts) and len(report_map) == len(shifts) and all(r.status == "submitted" and (r.stock_discrepancies_count or 0) == 0 for r in reports)
    conditional.append(("🟢" if cash_ok else "🟡") + f" 💵 Денежная дисциплина — +{CASH_DISCIPLINE_MONTHLY_BONUS:.0f} ₽" + (" — условие выполнено на сегодня; нужно сохранить до конца месяца" if cash_ok else "\n   Условие: все смены закрыты без отрицательной разницы по кассе"))
    conditional.append(("🟢" if ideal_ok else "🟡") + f" ⭐ Идеальное закрытие смен — +{IDEAL_CLOSE_MONTHLY_BONUS:.0f} ₽" + (" — условие выполнено на сегодня; нужно сохранить до конца месяца" if ideal_ok else "\n   Условие: все отчёты сданы без расхождений и с обязательной уборкой"))
    violations = (await session.execute(select(SalaryViolation).where(SalaryViolation.employee_id == employee_id, SalaryViolation.created_at >= start, SalaryViolation.created_at < end))).scalars().all()
    conditional.append(("🟢" if not violations else "🔴") + " 🌟 Без нарушений — +500 ₽\n   Условие: не получить нарушений до конца месяца")
    sales = Decimal("0.00")
    try:
        page = 1; shift_map = {int(s.langame_shift_id): s for s in shifts if s.langame_shift_id is not None}
        while True:
            result = await langame.product_sales(month_start.isoformat(), today.isoformat(), page=page, page_limit=100)
            rows = result.get("data") or result.get("items") or []
            if not rows: break
            for row in rows:
                if int(row.get("cancel", 0) or 0) == 1: continue
                sid = row.get("working_shift_id"); sh = shift_map.get(int(sid)) if sid is not None else None
                if sh is not None and sh.employee_id == employee_id: sales += Decimal(str(row.get("price_sale", 0) or 0)) * Decimal(str(row.get("count", 0) or 0))
            total_pages = result.get("total_pages")
            if not total_pages or page >= int(total_pages): break
            page += 1
    except Exception: pass
    if sales >= BAR_THRESHOLD:
        current_bar = (BAR_THRESHOLD * BAR_BASE_RATE) + ((sales - BAR_THRESHOLD) * BAR_EXCESS_RATE)
        earned.append(f"🍔 Бар — предварительно +{current_bar.quantize(MONEY)} ₽\n   Продажи сейчас: {sales.quantize(MONEY)} ₽")
    else:
        conditional.append(f"🟡 🍔 Бар — бонус начинается от 30 000 ₽\n   Продажи сейчас: {sales.quantize(MONEY)} ₽; осталось: {(BAR_THRESHOLD-sales).quantize(MONEY)} ₽")
    conditional.append("🟡 🏆 Топ продаж бара — ещё +5% от личных продаж\n   Условие: закончить месяц первым по продажам бара")
    conditional.append(f"🟡 🧹 Уборка — +{CLEANING_MONTHLY_BONUS:.0f} ₽\n   Условие: выполнить все назначенные уборки месяца")
    if earned: lines += ["🟢 УЖЕ ЗАРАБОТАНО / ЗАФИКСИРОВАНО", *earned, ""]
    lines += ["📌 БОНУСЫ ПО УСЛОВИЯМ", *conditional, "", "ℹ️ Месячные бонусы окончательно начисляются по итогам календарного месяца."]
    return "\n".join(lines)



async def _owner_bonus_dashboard(session) -> str:
    """Owner view: what is already recorded in salary calculations and what is
    currently achievable under the monthly bonus rules.
    """
    today = datetime.now(MOSCOW_TZ).date()
    month_start = today.replace(day=1)
    start = datetime.combine(month_start, time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc)

    employees = (await session.execute(
        select(Employee).where(Employee.active.is_(True)).order_by(Employee.full_name.asc())
    )).scalars().all()
    if not employees:
        return "🏆 <b>Бонусы администраторов</b>\n\nАктивных администраторов пока нет."

    employee_ids = [e.id for e in employees]
    shifts = (await session.execute(select(Shift).where(
        Shift.employee_id.in_(employee_ids), Shift.status == "closed",
        Shift.started_at >= start, Shift.started_at < end,
    ))).scalars().all()
    by_employee: dict[int, list[Shift]] = {eid: [] for eid in employee_ids}
    for sh in shifts:
        if sh.employee_id in by_employee:
            by_employee[sh.employee_id].append(sh)

    # Product sales are read-only from LANGAME and attributed through working_shift_id.
    sales_by_employee = {eid: Decimal("0.00") for eid in employee_ids}
    shift_map = {int(s.langame_shift_id): s for s in shifts if s.langame_shift_id is not None}
    try:
        page = 1
        while True:
            result = await langame.product_sales(month_start.isoformat(), today.isoformat(), page=page, page_limit=100)
            rows = result.get("data") or result.get("items") or []
            if not rows:
                break
            for row in rows:
                if int(row.get("cancel", 0) or 0) == 1:
                    continue
                sid = row.get("working_shift_id")
                sh = shift_map.get(int(sid)) if sid is not None else None
                if sh is None or sh.employee_id not in sales_by_employee:
                    continue
                sales_by_employee[sh.employee_id] += Decimal(str(row.get("price_sale", 0) or 0)) * Decimal(str(row.get("count", 0) or 0))
            total_pages = result.get("total_pages")
            if not total_pages or page >= int(total_pages):
                break
            page += 1
    except Exception:
        pass

    # Fixed/recorded positive salary adjustments for the current month.
    period_rows = (await session.execute(select(SalaryPeriod).where(
        SalaryPeriod.employee_id.in_(employee_ids),
        SalaryPeriod.date_from == month_start,
        SalaryPeriod.date_to == today,
    ))).scalars().all()
    period_ids = [p.id for p in period_rows]
    recorded_by_employee = {eid: Decimal("0.00") for eid in employee_ids}
    if period_ids:
        adjustments = (await session.execute(select(SalaryAdjustment).where(
            SalaryAdjustment.salary_period_id.in_(period_ids), SalaryAdjustment.amount > 0
        ))).scalars().all()
        period_owner = {p.id: p.employee_id for p in period_rows}
        for a in adjustments:
            eid = period_owner.get(a.salary_period_id)
            if eid in recorded_by_employee:
                recorded_by_employee[eid] += Decimal(a.amount)

    violations_by_employee = {eid: 0 for eid in employee_ids}
    violations = (await session.execute(select(SalaryViolation).where(
        SalaryViolation.employee_id.in_(employee_ids),
        SalaryViolation.created_at >= start, SalaryViolation.created_at < end,
    ))).scalars().all()
    for v in violations:
        violations_by_employee[v.employee_id] = violations_by_employee.get(v.employee_id, 0) + 1

    totals = {"recorded": Decimal("0.00"), "potential": Decimal("0.00"), "at_risk": 0}
    rows_text = []
    for e in employees:
        eid = e.id
        sales = sales_by_employee[eid]
        recorded = recorded_by_employee[eid]
        # Bar bonus becomes payable once 30k is reached. Current amount is a
        # preview; final monthly bonus is calculated at month close.
        bar_potential = Decimal("0.00")
        if sales >= BAR_THRESHOLD:
            bar_potential = (BAR_THRESHOLD * BAR_BASE_RATE) + ((sales - BAR_THRESHOLD) * BAR_EXCESS_RATE)
        no_violation = violations_by_employee[eid] == 0
        shifts_e = by_employee[eid]
        reports = []
        if shifts_e:
            reports = (await session.execute(select(ShiftCloseReport).where(
                ShiftCloseReport.shift_id.in_([s.id for s in shifts_e])
            ))).scalars().all()
        report_map = {r.shift_id: r for r in reports}
        cash_ok = bool(shifts_e) and len(report_map) == len(shifts_e) and all(
            r.status == "submitted" and r.cash_difference is not None and Decimal(r.cash_difference) >= 0 for r in reports
        )
        ideal_ok = bool(shifts_e) and len(report_map) == len(shifts_e) and all(
            r.status == "submitted" and (r.stock_discrepancies_count or 0) == 0 for r in reports
        )
        potential = bar_potential + (CASH_DISCIPLINE_MONTHLY_BONUS if cash_ok else Decimal("0")) + (IDEAL_CLOSE_MONTHLY_BONUS if ideal_ok else Decimal("0")) + (Decimal("500.00") if no_violation else Decimal("0"))
        status = "🟢" if no_violation and (cash_ok or ideal_ok or sales >= BAR_THRESHOLD) else "🟡"
        if violations_by_employee[eid]:
            status = "🔴"
            totals["at_risk"] += 1
        totals["recorded"] += recorded
        totals["potential"] += potential
        name = (e.full_name or f"Администратор #{eid}")[:32]
        rows_text.append(
            f"{status} <b>{name}</b>\n"
            f"   💰 Зафиксировано: +{recorded.quantize(MONEY)} ₽\n"
            f"   🎯 По условиям сейчас: до +{potential.quantize(MONEY)} ₽\n"
            f"   🍔 Бар: {sales.quantize(MONEY)} / {BAR_THRESHOLD.quantize(MONEY)} ₽\n"
            f"   💵 Дисциплина: {'🟢 выполнено' if cash_ok else '🟡 в процессе'} · "
            f"⭐ Закрытие: {'🟢 выполнено' if ideal_ok else '🟡 в процессе'}\n"
            f"   🌟 Без нарушений: {'🟢 пока да' if no_violation else '🔴 есть нарушение'}"
        )

    lines = [
        "🏆 <b>БОНУСЫ АДМИНИСТРАТОРОВ</b>",
        f"Период: {month_start:%d.%m.%Y} — {today:%d.%m.%Y}",
        "",
        f"💰 Зафиксировано в расчётах: <b>+{totals['recorded'].quantize(MONEY)} ₽</b>",
        f"🎯 Потенциал по текущим условиям: <b>+{totals['potential'].quantize(MONEY)} ₽</b>",
        f"⚠️ Администраторов с нарушениями: <b>{totals['at_risk']}</b>",
        "",
        *rows_text,
        "",
        "ℹ️ «По условиям сейчас» — это предварительный потенциал. Финальные месячные бонусы фиксируются по итогам календарного месяца.",
    ]
    return "\n".join(lines)


@router.message(F.text == "🏆 Бонусы")
async def owner_bonuses_view(message: Message):
    user = await get_access(message)
    if user is None or user.role != UserRole.OWNER.value:
        await message.answer("⛔ Только владелец.")
        return
    async with SessionLocal() as session:
        text = await _owner_bonus_dashboard(session)
    await message.answer(text)

@router.message(F.text == "🏆 Мои бонусы")
async def my_bonuses_view(message: Message):
    user = await get_access(message)
    if user is None:
        await message.answer("⛔ Доступ не настроен. Обратитесь к владельцу клуба."); return
    if user.role != UserRole.ADMIN.value:
        await message.answer("⛔ Этот раздел доступен администраторам."); return
    if user.employee_id is None:
        await message.answer("❌ Ваш Telegram пока не привязан к администратору."); return
    async with SessionLocal() as session: text = await _current_month_bonus_status(user.employee_id, session)
    await message.answer(text)

@router.message(F.text == "💰 Моя зарплата")
async def my_salary_view(message: Message):
    user = await get_access(message)
    if user is None:
        await message.answer("⛔ Доступ не настроен. Обратитесь к владельцу клуба.")
        return
    if user.employee_id is None:
        await message.answer("❌ Ваш Telegram пока не привязан к администратору.")
        return
    today = datetime.now(timezone.utc).date()
    date_from = today.replace(day=1)
    async with SessionLocal() as session:
        rate = await active_hourly_rate(session)
        if rate is None:
            await message.answer("ℹ️ Зарплата ещё не настроена владельцем.")
            return
        period = await calculate_period(user.employee_id, date_from, today, rate, session)
        employee_result = await session.execute(select(Employee).where(Employee.id == user.employee_id))
        employee = employee_result.scalar_one()
        await session.commit()
    await message.answer(
        f"💰 {employee.full_name or employee.langame_user_id}\n"
        f"Период: {date_from} — {today}\n"
        f"Оплата: {rate} ₽ за смену\n"
        f"Начислено: {period.total_amount} ₽\n"
        f"Статус: {period.status}"
    )


@router.message(F.text == "💰 Зарплата")
async def salary_menu(message: Message):
    if not await owner_only(message):
        return
    async with SessionLocal() as session:
        rate = await active_hourly_rate(session)
        result = await session.execute(select(SalaryPeriod).order_by(SalaryPeriod.id.desc()).limit(5))
        periods = result.scalars().all()
    text = ["💰 Управление зарплатой", f"Фиксированная оплата: {rate} ₽ за смену"]
    if periods:
        text += ["", "Последние расчёты:"]
        text += [f"#{p.id} · адм. {p.employee_id} · {p.date_from} — {p.date_to} · {p.total_amount} ₽ · {p.status}" for p in periods]
    await message.answer("\n".join(text), reply_markup=salary_main_keyboard())


@router.callback_query(F.data == "salary_sync")
async def salary_sync_callback(callback: CallbackQuery):
    if not await owner_only(callback.message):
        await callback.answer()
        return
    try:
        created, updated, skipped = await sync_shifts_data()
        await callback.message.answer(f"✅ Смены обновлены из LANGAME.\nНовых: {created}\nОбновлено: {updated}\nПропущено: {skipped}")
    except Exception as exc:
        await callback.message.answer(f"❌ Ошибка синхронизации: {str(exc)[:300]}")
    await callback.answer()


@router.callback_query(F.data == "salary_employees")
async def salary_employees_callback(callback: CallbackQuery):
    if not await owner_only(callback.message):
        await callback.answer()
        return
    async with SessionLocal() as session:
        result = await session.execute(select(Employee).where(Employee.active.is_(True)).order_by(Employee.full_name.asc()))
        employees = result.scalars().all()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=(e.full_name or f"Администратор #{e.id}")[:50], callback_data=f"salary_emp:{e.id}")] for e in employees
    ])
    await callback.message.answer("👥 Выберите администратора:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("salary_emp:"))
async def salary_employee_callback(callback: CallbackQuery, state: FSMContext):
    if not await owner_only(callback.message):
        await callback.answer()
        return
    employee_id = int(callback.data.split(":")[1])
    await state.update_data(employee_id=employee_id)
    await state.set_state(SalaryUIState.waiting_period)
    await callback.message.answer("📅 Введите период одной строкой:\nYYYY-MM-DD YYYY-MM-DD\nНапример: 2026-09-01 2026-09-30")
    await callback.answer()


@router.callback_query(F.data == "salary_period_ui")
async def salary_period_ui(callback: CallbackQuery, state: FSMContext):
    if not await owner_only(callback.message):
        await callback.answer()
        return
    async with SessionLocal() as session:
        result = await session.execute(select(Employee).where(Employee.active.is_(True)).order_by(Employee.full_name.asc()))
        employees = result.scalars().all()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=(e.full_name or f"Администратор #{e.id}")[:50], callback_data=f"salary_emp:{e.id}")] for e in employees
    ])
    await callback.message.answer("👥 Сначала выберите администратора:", reply_markup=kb)
    await callback.answer()


@router.message(SalaryUIState.waiting_period)
async def salary_period_input(message: Message, state: FSMContext):
    user = await owner_only(message)
    if user is None:
        await state.clear(); return
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("❌ Формат: YYYY-MM-DD YYYY-MM-DD")
        return
    try:
        date_from, date_to = parse_date(parts[0]), parse_date(parts[1])
        if date_to < date_from:
            raise ValueError
    except ValueError:
        await message.answer("❌ Неверный период.")
        return
    data = await state.get_data()
    employee_id = data.get("employee_id")
    async with SessionLocal() as session:
        employee_result = await session.execute(select(Employee).where(Employee.id == employee_id))
        employee = employee_result.scalar_one_or_none()
        rate = await active_hourly_rate(session)
        if employee is None or rate is None:
            await message.answer("❌ Сотрудник не найден.")
            await state.clear(); return
        period = await calculate_period(employee.id, date_from, date_to, rate, session)
        shifts_result = await session.execute(select(Shift).where(Shift.employee_id == employee.id, Shift.status == "closed", Shift.started_at >= datetime.combine(date_from, time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc), Shift.started_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=MOSCOW_TZ).astimezone(timezone.utc)))
        shifts = shifts_result.scalars().all()
        hours = sum((Decimal(str((x.ended_at - x.started_at).total_seconds())) / Decimal("3600") for x in shifts if x.ended_at), Decimal("0"))
        period._shift_count = len(shifts)
        await session.commit()
        text = format_period(period, employee, hours, rate)
        period_id = period.id
    await state.clear()
    await message.answer(text, reply_markup=salary_keyboard(period_id))


@router.callback_query(F.data == "salary_review_bonus_ui")
async def salary_review_bonus_ui(callback: CallbackQuery, state: FSMContext):
    if not await owner_only(callback.message):
        await callback.answer(); return
    async with SessionLocal() as session:
        employees = (await session.execute(select(Employee).where(Employee.active.is_(True)).order_by(Employee.full_name.asc()))).scalars().all()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=(e.full_name or f"Администратор #{e.id}")[:50], callback_data=f"salary_review_bonus_emp:{e.id}")] for e in employees
    ])
    await callback.message.answer("⭐ Выберите администратора для нефинансового бонуса за отзыв:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("salary_review_bonus_emp:"))
async def salary_review_bonus_emp(callback: CallbackQuery, state: FSMContext):
    if not await owner_only(callback.message):
        await callback.answer(); return
    employee_id = int(callback.data.split(":")[1])
    await state.update_data(review_bonus_employee_id=employee_id)
    await state.set_state(SalaryUIState.waiting_review_bonus)
    await callback.message.answer("📝 Укажите комментарий к бонусу за отзыв. Например: «Отзыв гостя, подтверждён владельцем».")
    await callback.answer()


@router.message(SalaryUIState.waiting_review_bonus)
async def salary_review_bonus_input(message: Message, state: FSMContext):
    user = await owner_only(message)
    if user is None:
        await state.clear(); return
    comment = (message.text or "").strip()
    if not comment:
        await message.answer("❌ Комментарий не может быть пустым.")
        return
    data = await state.get_data()
    employee_id = int(data["review_bonus_employee_id"])
    async with SessionLocal() as session:
        employee = await session.get(Employee, employee_id)
        if employee is None:
            await state.clear(); await message.answer("❌ Администратор не найден."); return
        session.add(NonMonetaryBonus(
            employee_id=employee_id, bonus_type="review",
            title="Бонус за отзыв гостя", comment=comment[:4000],
            created_by=message.from_user.id,
        ))
        await write_audit(session, actor_telegram_id=message.from_user.id, action="non_monetary_bonus_added", entity_type="employee", entity_id=str(employee_id), payload={"type":"review","comment":comment[:4000]})
        await session.commit()
    await state.clear()
    await message.answer(f"⭐ Нефинансовый бонус за отзыв зафиксирован для {employee.full_name or employee.langame_user_id}. Денежная сумма зарплаты не изменена.")


@router.callback_query(F.data.startswith("salary_adj:"))
async def salary_adjustment_callback(callback: CallbackQuery, state: FSMContext):
    if not await owner_only(callback.message):
        await callback.answer(); return
    _, period_id, sign = callback.data.split(":")
    await state.update_data(period_id=int(period_id), adjustment_sign=sign)
    await state.set_state(SalaryUIState.waiting_adjustment)
    await callback.message.answer("Введите сумму и причину, например:\n500 Премия за лучший результат\nили\n200 Штраф за опоздание")
    await callback.answer()


@router.message(SalaryUIState.waiting_adjustment)
async def salary_adjustment_input(message: Message, state: FSMContext):
    user = await owner_only(message)
    if user is None:
        await state.clear(); return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("❌ Формат: сумма причина")
        return
    try:
        amount = Decimal(parts[0].replace(",", "."))
        if amount <= 0: raise ValueError
    except ValueError:
        await message.answer("❌ Сумма должна быть положительным числом.")
        return
    data = await state.get_data()
    if data.get("adjustment_sign") == "minus":
        amount = -amount
    async with SessionLocal() as session:
        result = await session.execute(select(SalaryPeriod).where(SalaryPeriod.id == int(data["period_id"])))
        period = result.scalar_one_or_none()
        if period is None or period.status == "paid":
            await message.answer("❌ Период не найден или уже выплачен.")
            await state.clear(); return
        session.add(SalaryAdjustment(salary_period_id=period.id, amount=amount.quantize(MONEY), reason=parts[1], created_by=message.from_user.id))
        rate = await active_hourly_rate(session)
        period = await calculate_period(period.employee_id, period.date_from, period.date_to, rate, session)
        employee_result = await session.execute(select(Employee).where(Employee.id == period.employee_id))
        employee = employee_result.scalar_one()
        shifts_result = await session.execute(select(Shift).where(Shift.employee_id == employee.id, Shift.status == "closed", Shift.started_at >= datetime.combine(period.date_from, time.min, tzinfo=timezone.utc), Shift.started_at < datetime.combine(period.date_to, time.max, tzinfo=timezone.utc)))
        shifts = shifts_result.scalars().all()
        hours = sum((Decimal(str((x.ended_at-x.started_at).total_seconds()))/Decimal("3600") for x in shifts if x.ended_at), Decimal("0"))
        await write_audit(session, actor_telegram_id=message.from_user.id, action="salary_adjustment_added", entity_type="salary_period", entity_id=str(period.id), payload={"amount": str(amount), "reason": parts[1]})
        await session.commit()
    await state.clear()
    await message.answer(format_period(period, employee, hours, rate), reply_markup=salary_keyboard(period.id))


@router.callback_query(F.data.startswith("salary_confirm:"))
async def salary_confirm_callback(callback: CallbackQuery):
    if not await owner_only(callback.message):
        await callback.answer(); return
    period_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        result = await session.execute(select(SalaryPeriod).where(SalaryPeriod.id == period_id))
        period = result.scalar_one_or_none()
        if period is None:
            await callback.message.answer("❌ Период не найден.")
        elif period.status == "paid":
            await callback.message.answer("ℹ️ Период уже выплачен.")
        else:
            period.status = "confirmed"
            period.confirmed_by = callback.from_user.id
            period.confirmed_at = datetime.now(timezone.utc)
            await write_audit(session, actor_telegram_id=callback.from_user.id, action="salary_period_confirmed", entity_type="salary_period", entity_id=str(period.id), payload={"total": str(period.total_amount)})
            await session.commit()
            await callback.message.answer(f"✅ Период #{period_id} подтверждён: {period.total_amount} ₽.", reply_markup=salary_keyboard(period_id))
    await callback.answer()


@router.callback_query(F.data.startswith("salary_pay:"))
async def salary_pay_callback(callback: CallbackQuery):
    if not await owner_only(callback.message):
        await callback.answer(); return
    period_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        result = await session.execute(select(SalaryPeriod).where(SalaryPeriod.id == period_id))
        period = result.scalar_one_or_none()
        if period is None or period.status != "confirmed":
            await callback.message.answer("❌ Выплату можно провести только для подтверждённого периода.")
        else:
            existing = await session.execute(select(SalaryPayment).where(SalaryPayment.salary_period_id == period.id))
            if existing.scalar_one_or_none():
                await callback.message.answer("ℹ️ Выплата уже зарегистрирована.")
            else:
                session.add(SalaryPayment(salary_period_id=period.id, amount=period.total_amount, paid_by=callback.from_user.id))
                period.status = "paid"
                await write_audit(session, actor_telegram_id=callback.from_user.id, action="salary_paid", entity_type="salary_period", entity_id=str(period.id), payload={"amount": str(period.total_amount)})
                await session.commit()
                await callback.message.answer(f"💸 Выплата по периоду #{period_id} зарегистрирована: {period.total_amount} ₽.")
    await callback.answer()
