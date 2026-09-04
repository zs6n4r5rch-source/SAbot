from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import (
    CampaignStatus, Club, Discrepancy, Employee, Guest, GuestTelegram,
    InventoryBalance, InventoryOperation, Product, SalaryPeriod, Shift, WriteoffStatus,
    TelegramUser, UserRole, Writeoff, WriteoffItem,
)
from app.services.langame import LangameClient, langame_client

router = Router()
langame = langame_client


def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 7 дней", callback_data="analytics:7"), InlineKeyboardButton(text="📅 30 дней", callback_data="analytics:30")],
        [InlineKeyboardButton(text="📅 Этот месяц", callback_data="analytics:month")],
        [InlineKeyboardButton(text="📈 Продажи бара и снеков", callback_data="analytics:sales"), InlineKeyboardButton(text="🍔 Бар и снеки", callback_data="analytics:inventory")],
        [InlineKeyboardButton(text="👥 Администраторы", callback_data="analytics:admins"), InlineKeyboardButton(text="💰 Зарплата", callback_data="analytics:salary")],
        [InlineKeyboardButton(text="👤 Клиенты", callback_data="analytics:clients")],
        [InlineKeyboardButton(text="📅 По дням", callback_data="analytics:days"), InlineKeyboardButton(text="🏢 По клубам", callback_data="analytics:clubs")],
        [InlineKeyboardButton(text="📥 Excel", callback_data="analytics:excel")],
    ])


async def owner(message: Message | CallbackQuery) -> bool:
    uid = message.from_user.id if message.from_user else None
    if uid is None:
        return False
    async with SessionLocal() as session:
        user = (await session.execute(select(TelegramUser).where(TelegramUser.telegram_id == uid))).scalar_one_or_none()
        return bool(user and user.active and user.role == UserRole.OWNER.value)


def period_days(kind: str) -> tuple[datetime, datetime, str]:
    now = datetime.now(timezone.utc)
    if kind == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now, "текущий месяц"
    days = int(kind)
    return now - timedelta(days=days), now, f"последние {days} дней"


async def sales_rows(start: datetime, end: datetime):
    """Read product sales from LANGAME and return normalized rows.

    LANGAME's ProductsExpenseResponseDTO exposes working_shift_id, count,
    price_sale and cancel, so sales can be attributed to the corresponding
    local Shift/Employee without writing anything back to LANGAME.
    """
    rows_all = []
    page = 1
    while True:
        result = await langame.product_sales(
            start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
            page=page, page_limit=100
        )
        rows = result.get("data") or result.get("items") or []
        if not rows:
            break
        rows_all.extend(rows)
        total_pages = result.get("total_pages")
        if not total_pages or page >= int(total_pages):
            break
        page += 1
    return rows_all


async def sales_totals(start: datetime, end: datetime):
    total = Decimal("0")
    units = Decimal("0")
    rows = await sales_rows(start, end)
    for row in rows:
        if int(row.get("cancel", 0) or 0) == 1:
            continue
        try:
            qty = Decimal(str(row.get("count", 0) or 0))
            units += qty
            price = Decimal(str(row.get("price_sale", 0) or 0))
            total += price * qty
        except Exception:
            continue
    return total, units, len(rows)


async def admin_report(employee_id: int, days: int) -> str:
    start = datetime.now(timezone.utc) - timedelta(days=days)
    end = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        employee = await session.get(Employee, employee_id)
        if not employee:
            return "❌ Администратор не найден."
        shift_rows = (await session.execute(
            select(Shift, Club).join(Club, Club.id == Shift.club_id)
            .where(Shift.employee_id == employee_id, Shift.started_at >= start, Shift.started_at <= end)
            .order_by(Shift.started_at.desc())
        )).all()
        writeoff_units = await session.scalar(
            select(func.coalesce(func.sum(WriteoffItem.quantity), 0))
            .join(Writeoff, Writeoff.id == WriteoffItem.writeoff_id)
            .where(Writeoff.employee_id == employee_id, Writeoff.created_at >= start, Writeoff.created_at <= end,
                   Writeoff.status == WriteoffStatus.APPROVED.value)
        ) or 0
        discrepancy_count = await session.scalar(
            select(func.count(Discrepancy.id)).where(
                Discrepancy.employee_id == employee_id,
                Discrepancy.created_at >= start, Discrepancy.created_at <= end)
        ) or 0
        discrepancy_amount = await session.scalar(
            select(func.coalesce(func.sum(Discrepancy.amount_difference), 0)).where(
                Discrepancy.employee_id == employee_id,
                Discrepancy.created_at >= start, Discrepancy.created_at <= end)
        ) or 0
        periods = (await session.execute(
            select(SalaryPeriod).where(
                SalaryPeriod.employee_id == employee_id,
                SalaryPeriod.date_from <= end.date(), SalaryPeriod.date_to >= start.date())
        )).scalars().all()
        salary = sum((Decimal(str(x.total_amount or 0)) for x in periods), Decimal("0"))

    shift_ids = {int(sh.langame_shift_id) for sh, _ in shift_rows}
    sales = await sales_rows(start, end)
    sales_by_shift: dict[int, Decimal] = {}
    units_by_shift: dict[int, Decimal] = {}
    for row in sales:
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
    cash_diff = Decimal("0")
    sales_total = Decimal("0")
    sold_units = Decimal("0")
    lines = [f"👤 <b>{employee.full_name or f'Администратор #{employee.id}'}</b>", f"Период: последние {days} дней", ""]
    for sh, club in shift_rows:
        h = Decimal("0")
        if sh.ended_at and sh.ended_at > sh.started_at:
            h = Decimal(str((sh.ended_at - sh.started_at).total_seconds())) / Decimal("3600")
        hours += h
        cash_diff += Decimal(str(sh.cash_difference or 0))
        sid = int(sh.langame_shift_id)
        amount = sales_by_shift.get(sid, Decimal("0"))
        units = units_by_shift.get(sid, Decimal("0"))
        sales_total += amount
        sold_units += units
        status = "закрыта" if sh.status == "closed" else "открыта"
        lines.append(f"• смена #{sid} · {club.name} · {status} · {h:.1f} ч · продажи {amount:.2f} ₽ / {units:g} ед.")

    lines.extend([
        "", f"📋 Смен: <b>{len(shift_rows)}</b>", f"⏱ Часы: <b>{hours:.1f}</b>",
        f"📈 Продажи: <b>{sales_total:.2f} ₽</b> · {sold_units:g} ед.",
        f"💵 Разница по кассе: <b>{cash_diff:.2f} ₽</b>",
        f"🗑 Одобренные списания: <b>{Decimal(str(writeoff_units)):g} ед.</b>",
        f"⚠️ Расхождения: <b>{discrepancy_count}</b> · сумма {Decimal(str(discrepancy_amount)):.2f} ₽",
        f"💰 Зарплата в пересекающихся периодах: <b>{salary:.2f} ₽</b>",
    ])
    return "\n".join(lines)


async def shift_report(shift_id: int) -> str:
    async with SessionLocal() as session:
        row = (await session.execute(
            select(Shift, Employee, Club).join(Club, Club.id == Shift.club_id)
            .outerjoin(Employee, Employee.id == Shift.employee_id)
            .where(Shift.id == shift_id)
        )).first()
        if not row:
            return "❌ Смена не найдена."
        sh, employee, club = row
    sales = await sales_rows(sh.started_at, sh.ended_at or datetime.now(timezone.utc))
    total = Decimal("0")
    units = Decimal("0")
    for x in sales:
        if int(x.get("cancel", 0) or 0) == 1 or int(x.get("working_shift_id", -1)) != int(sh.langame_shift_id):
            continue
        try:
            qty = Decimal(str(x.get("count", 0) or 0))
            units += qty
            total += Decimal(str(x.get("price_sale", 0) or 0)) * qty
        except Exception:
            pass
    hours = Decimal("0")
    if sh.ended_at and sh.ended_at > sh.started_at:
        hours = Decimal(str((sh.ended_at - sh.started_at).total_seconds())) / Decimal("3600")
    end_text = f"{sh.ended_at:%Y-%m-%d %H:%M}" if sh.ended_at else "ещё не закрыта"
    return (f"🕒 <b>Смена #{sh.langame_shift_id}</b>\n\n"
            f"👤 Администратор: {employee.full_name if employee else 'не привязан'}\n"
            f"🏢 Клуб: {club.name}\n"
            f"📅 Начало: {sh.started_at:%Y-%m-%d %H:%M}\n"
            f"📅 Конец: {end_text}\n"
            f"⏱ Часы: <b>{hours:.2f}</b>\n"
            f"📈 Продажи товаров: <b>{total:.2f} ₽</b> · {units:g} ед.\n"
            f"💵 Разница кассы: <b>{Decimal(str(sh.cash_difference or 0)):.2f} ₽</b>")


async def admins_ranking(days: int):
    start = datetime.now(timezone.utc) - timedelta(days=days)
    end = datetime.now(timezone.utc)
    sales = await sales_rows(start, end)
    sales_by_shift: dict[int, Decimal] = {}
    for row in sales:
        if int(row.get("cancel", 0) or 0) == 1:
            continue
        sid = row.get("working_shift_id")
        if sid is None:
            continue
        try:
            sales_by_shift[int(sid)] = sales_by_shift.get(int(sid), Decimal("0")) + Decimal(str(row.get("price_sale", 0) or 0)) * Decimal(str(row.get("count", 0) or 0))
        except Exception:
            pass
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(Employee, Shift).outerjoin(Shift, Shift.employee_id == Employee.id).where(
                Shift.started_at >= start, Shift.started_at <= end
            ).order_by(Employee.full_name)
        )).all()
        # Keep employees without shifts in the ranking too.
        employees = (await session.execute(select(Employee).order_by(Employee.full_name))).scalars().all()
    stats: dict[int, dict] = {e.id: {"name": e.full_name or f"Администратор #{e.id}", "shifts": 0, "hours": Decimal("0"), "sales": Decimal("0")} for e in employees}
    for emp, sh in rows:
        st = stats[emp.id]
        st["shifts"] += 1
        if sh.ended_at and sh.ended_at > sh.started_at:
            st["hours"] += Decimal(str((sh.ended_at - sh.started_at).total_seconds())) / Decimal("3600")
        st["sales"] += sales_by_shift.get(int(sh.langame_shift_id), Decimal("0"))
    ranked = sorted(stats.values(), key=lambda x: (x["sales"], x["hours"]), reverse=True)
    lines = [f"👥 <b>Администраторы — рейтинг за {days} дней</b>", "", "Продажи товаров привязаны к администратору через LANGAME → смену.", ""]
    buttons = []
    for i, st in enumerate(ranked[:20], 1):
        per_hour = st["sales"] / st["hours"] if st["hours"] > 0 else Decimal("0")
        lines.append(f"{i}. <b>{st['name']}</b> — {st['sales']:.2f} ₽ · {st['hours']:.1f} ч · {st['shifts']} смен · {per_hour:.2f} ₽/ч")
    for st in ranked[:20]:
        emp_id = next((eid for eid, x in stats.items() if x is st), None)
        if emp_id:
            buttons.append([InlineKeyboardButton(text=f"🔎 {st['name'][:38]}", callback_data=f"analytics_admin:{emp_id}:{days}")])
    return "\n".join(lines), buttons


async def report(kind: str) -> str:
    start, end, label = period_days(kind)
    sales, sold_units, sales_rows = await sales_totals(start, end)
    async with SessionLocal() as session:
        shifts = await session.scalar(select(func.count(Shift.id)).where(Shift.started_at >= start, Shift.started_at <= end)) or 0
        closed_shifts = await session.scalar(select(func.count(Shift.id)).where(Shift.started_at >= start, Shift.started_at <= end, Shift.status == "closed")) or 0
        hours_rows = (await session.execute(select(Shift.started_at, Shift.ended_at).where(Shift.started_at >= start, Shift.started_at <= end, Shift.status == "closed"))).all()
        hours = sum((Decimal(str((e - s).total_seconds())) / Decimal("3600") for s, e in hours_rows if e and e > s), Decimal("0"))
        writeoffs = await session.scalar(select(func.count(Writeoff.id)).where(Writeoff.created_at >= start, Writeoff.created_at <= end, Writeoff.status == "approved")) or 0
        writeoff_units = await session.scalar(select(func.coalesce(func.sum(WriteoffItem.quantity), 0)).join(Writeoff, Writeoff.id == WriteoffItem.writeoff_id).where(Writeoff.created_at >= start, Writeoff.created_at <= end, Writeoff.status == "approved")) or 0
        discrepancies = await session.scalar(select(func.count(Discrepancy.id)).where(Discrepancy.created_at >= start, Discrepancy.created_at <= end)) or 0
        resolved = await session.scalar(select(func.count(Discrepancy.id)).where(Discrepancy.created_at >= start, Discrepancy.created_at <= end, Discrepancy.status == "resolved")) or 0
        admins = await session.scalar(select(func.count(Employee.id)).where(Employee.active.is_(True))) or 0
        linked = await session.scalar(select(func.count(GuestTelegram.id))) or 0
        consent = await session.scalar(select(func.count(GuestTelegram.id)).where(GuestTelegram.marketing_consent.is_(True))) or 0
        guests = await session.scalar(select(func.count(Guest.id))) or 0
        paid = await session.scalar(select(func.coalesce(func.sum(SalaryPeriod.total_amount), 0)).where(SalaryPeriod.date_from <= end.date(), SalaryPeriod.date_to >= start.date())) or 0
        low_stock = await session.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock)) or 0

    return (
        f"📊 <b>Сводная аналитика — {label}</b>\n\n"
        f"💵 Продажи: <b>{sales:.2f}</b>\n"
        f"📦 Продано единиц: <b>{sold_units:g}</b>\n"
        f"🧾 Строк продаж LANGAME: {sales_rows}\n\n"
        f"📋 Смены: <b>{shifts}</b> (закрыто {closed_shifts})\n"
        f"⏱ Отработано: <b>{hours:.1f} ч</b>\n\n"
        f"🗑 Списания: <b>{writeoffs}</b> операций / {writeoff_units:g} ед.\n"
        f"⚠️ Расхождения: <b>{discrepancies}</b> (решено {resolved})\n"
        f"📉 Товаров ниже минимума: <b>{low_stock}</b>\n\n"
        f"👥 Администраторов: <b>{admins}</b>\n"
        f"👤 Клиентов в кэше: <b>{guests}</b>\n"
        f"💬 Telegram-привязок: <b>{linked}</b>\n"
        f"📣 Согласий на маркетинг: <b>{consent}</b>\n\n"
        f"💰 Зарплата в пересекающихся периодах: <b>{Decimal(str(paid)):.2f}</b>"
    )


async def daily_report_for_window(start: datetime, end: datetime, label: str, *, include_sales=True, include_shifts=True, include_inventory=True, include_discrepancies=True, include_salary=True, include_clients=True) -> str:
    """Operational analytics for an exact UTC window."""
    sales = await sales_rows(start, end)
    async with SessionLocal() as session:
        shift_rows = (await session.execute(
            select(Shift, Club).join(Club, Club.id == Shift.club_id).where(
                Shift.started_at >= start, Shift.started_at < end
            )
        )).all()
        writeoff_rows = (await session.execute(
            select(Writeoff.created_at, WriteoffItem.quantity).join(
                WriteoffItem, WriteoffItem.writeoff_id == Writeoff.id
            ).where(
                Writeoff.created_at >= start, Writeoff.created_at < end,
                Writeoff.status == WriteoffStatus.APPROVED.value
            )
        )).all()
        discrepancy_rows = (await session.execute(
            select(Discrepancy.created_at, Discrepancy.quantity_difference, Discrepancy.amount_difference)
            .where(Discrepancy.created_at >= start, Discrepancy.created_at < end)
        )).all()

    by_shift = {}
    for row in sales:
        if int(row.get("cancel", 0) or 0) == 1 or row.get("working_shift_id") is None:
            continue
        try:
            sid = int(row["working_shift_id"])
            qty = Decimal(str(row.get("count", 0) or 0))
            amount = Decimal(str(row.get("price_sale", 0) or 0)) * qty
            item = by_shift.setdefault(sid, [Decimal("0"), Decimal("0")])
            item[0] += amount
            item[1] += qty
        except (TypeError, ValueError, ArithmeticError):
            continue

    sales_total = sum((x[0] for x in by_shift.values()), Decimal("0"))
    units_total = sum((x[1] for x in by_shift.values()), Decimal("0"))
    hours = Decimal("0")
    closed = 0
    for sh, _ in shift_rows:
        if sh.status == "closed":
            closed += 1
        if sh.ended_at and sh.ended_at > sh.started_at:
            hours += Decimal(str((sh.ended_at - sh.started_at).total_seconds())) / Decimal("3600")
    writeoff_units = sum((Decimal(str(qty or 0)) for _, qty in writeoff_rows), Decimal("0"))
    diff_count = len(discrepancy_rows)
    diff_amount = sum((Decimal(str(amount or 0)) for _, _, amount in discrepancy_rows), Decimal("0"))
    lines = [f"📊 <b>Ежедневный отчёт — {label}</b>", ""]
    if include_sales:
        lines += [f"📈 Товарные продажи LANGAME: <b>{sales_total:.2f} ₽</b>", f"📦 Продано единиц: <b>{units_total:g}</b>", ""]
    if include_shifts:
        lines += [f"📋 Смен: <b>{len(shift_rows)}</b> · закрыто {closed}", f"⏱ Отработано: <b>{hours:.1f} ч</b>", ""]
    if include_inventory:
        lines += [f"🗑 Одобренные списания: <b>{writeoff_units:g} ед.</b>", ""]
    if include_discrepancies:
        lines += [f"⚠️ Расхождения: <b>{diff_count}</b> · {diff_amount:.2f} ₽", ""]
    if include_salary:
        lines += ["💰 Зарплата: см. расчётные периоды в разделе «Зарплата». ", ""]
    if include_clients:
        async with SessionLocal() as session:
            guest_count = await session.scalar(select(func.count(Guest.id))) or 0
            consent_count = await session.scalar(select(func.count(GuestTelegram.id)).where(GuestTelegram.marketing_consent.is_(True))) or 0
        lines += [f"👤 Клиенты: <b>{guest_count}</b> · согласий на маркетинг <b>{consent_count}</b>", ""]
    lines += ["⚠️ Продажи — именно товарные продажи из LANGAME, не общая выручка клуба."]
    return "\n".join(lines)


async def daily_report(days: int = 30) -> str:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    return await daily_report_for_window(start, end, f"последние {days} дней")


async def club_report(days: int = 30) -> str:
    """Club comparison using local shift-to-club mapping and LANGAME product sales."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    sales = await sales_rows(start, end)
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(Shift, Club).join(Club, Club.id == Shift.club_id).where(
                Shift.started_at >= start, Shift.started_at <= end
            )
        )).all()
        writeoffs = (await session.execute(
            select(Writeoff.club_id, func.coalesce(func.sum(WriteoffItem.quantity), 0))
            .join(WriteoffItem, WriteoffItem.writeoff_id == Writeoff.id)
            .where(Writeoff.created_at >= start, Writeoff.created_at <= end, Writeoff.status == WriteoffStatus.APPROVED.value)
            .group_by(Writeoff.club_id)
        )).all()
        discrepancies = (await session.execute(
            select(Discrepancy.club_id, func.count(Discrepancy.id), func.coalesce(func.sum(Discrepancy.amount_difference), 0))
            .where(Discrepancy.created_at >= start, Discrepancy.created_at <= end)
            .group_by(Discrepancy.club_id)
        )).all()

    shift_map = {int(sh.langame_shift_id): (club.id, club.name) for sh, club in rows}
    stats = {}
    for row in sales:
        if int(row.get("cancel", 0) or 0) == 1 or row.get("working_shift_id") is None:
            continue
        try:
            club_id, club_name = shift_map[int(row["working_shift_id"])]
            qty = Decimal(str(row.get("count", 0) or 0))
            amount = Decimal(str(row.get("price_sale", 0) or 0)) * qty
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
        x = stats.setdefault(club_id, {"name": club_name, "sales": Decimal("0"), "units": Decimal("0"), "hours": Decimal("0"), "shifts": 0, "writeoffs": Decimal("0"), "discrepancies": 0, "diff": Decimal("0")})
        x["sales"] += amount
        x["units"] += qty

    for sh, club in rows:
        x = stats.setdefault(club.id, {"name": club.name, "sales": Decimal("0"), "units": Decimal("0"), "hours": Decimal("0"), "shifts": 0, "writeoffs": Decimal("0"), "discrepancies": 0, "diff": Decimal("0")})
        x["shifts"] += 1
        if sh.ended_at and sh.ended_at > sh.started_at:
            x["hours"] += Decimal(str((sh.ended_at - sh.started_at).total_seconds())) / Decimal("3600")
    for club_id, qty in writeoffs:
        if club_id in stats:
            stats[club_id]["writeoffs"] = Decimal(str(qty or 0))
    for club_id, count, amount in discrepancies:
        if club_id in stats:
            stats[club_id]["discrepancies"] = int(count or 0)
            stats[club_id]["diff"] = Decimal(str(amount or 0))

    lines = [f"🏢 <b>Аналитика по клубам — {days} дней</b>", "", "Продажи — только товарные продажи LANGAME.", ""]
    ranked = sorted(stats.values(), key=lambda x: x["sales"], reverse=True)
    for i, x in enumerate(ranked, 1):
        per_hour = x["sales"] / x["hours"] if x["hours"] > 0 else Decimal("0")
        lines.append(
            f"{i}. <b>{x['name']}</b> — {x['sales']:.2f} ₽ · {x['units']:g} ед. · "
            f"{x['hours']:.1f} ч · {x['shifts']} смен · {per_hour:.2f} ₽/ч · "
            f"списания {x['writeoffs']:g} · расхождения {x['discrepancies']}"
        )
    return "\n".join(lines) if len(lines) > 4 else "🏢 Клубов с данными за период пока нет."


@router.message(F.text == "📊 Аналитика")
async def analytics_menu(message: Message):
    if not await owner(message):
        await message.answer("⛔ Доступ только для владельца.")
        return
    await message.answer("📊 Аналитика владельца\n\nВыберите период или раздел:", reply_markup=menu_keyboard())


@router.callback_query(F.data.startswith("analytics:"))
async def analytics_callback(callback: CallbackQuery):
    if not await owner(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    key = callback.data.split(":", 1)[1]
    if key == "excel":
        try:
            from aiogram.types import FSInputFile
            from app.bot.analytics_export import build_excel
            path = await build_excel(30)
            await callback.message.answer_document(FSInputFile(path), caption="📊 Excel-отчёт владельца за последние 30 дней")
        except Exception as exc:
            await callback.message.answer(f"❌ Не удалось сформировать Excel: {str(exc)[:500]}")
        await callback.answer()
        return
    if key in {"7", "30", "month"}:
        try:
            text = await report(key)
        except Exception as exc:
            text = f"❌ Не удалось построить отчёт: {str(exc)[:500]}"
        await callback.message.answer(text, reply_markup=menu_keyboard())
        await callback.answer()
        return
    if key == "sales":
        await callback.message.answer("📈 Продажи бара и снеков\n\nПоказываю продажи напрямую из LANGAME. Выберите период:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="7 дней", callback_data="analytics:7"), InlineKeyboardButton(text="30 дней", callback_data="analytics:30")], [InlineKeyboardButton(text="Этот месяц", callback_data="analytics:month")]]))
    elif key == "inventory":
        async with SessionLocal() as session:
            rows = (await session.execute(select(Product.name, InventoryBalance.quantity, InventoryBalance.min_stock, Club.name).join(Product, Product.id == InventoryBalance.product_id).join(Club, Club.id == InventoryBalance.club_id).order_by(InventoryBalance.quantity).limit(30))).all()
        lines = ["🍔 Бар и снеки — критические остатки:"]
        for name, qty, minimum, club in rows:
            flag = " ⚠️" if minimum and qty <= minimum else ""
            lines.append(f"• {club}: {name} — {qty:g} / мин. {minimum:g}{flag}")
        await callback.message.answer("\n".join(lines) if len(lines) > 1 else "📦 Остатки бара и снеков пока не синхронизированы.")
    elif key == "admins":
        text, buttons = await admins_ranking(30)
        await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons or [[InlineKeyboardButton(text="Нет администраторов", callback_data="analytics:none")]]))
    elif key == "salary":
        async with SessionLocal() as session:
            rows = (await session.execute(select(Employee.full_name, func.coalesce(func.sum(SalaryPeriod.total_amount), 0)).join(SalaryPeriod, SalaryPeriod.employee_id == Employee.id).group_by(Employee.id).order_by(Employee.full_name))).all()
        lines = ["💰 Зарплата по администраторам:"]
        for name, amount in rows:
            lines.append(f"• {name or 'Без ФИО'} — {Decimal(str(amount)):.2f}")
        await callback.message.answer("\n".join(lines) if len(lines) > 1 else "Расчётов зарплаты пока нет.")
    elif key == "days":
        try:
            text = await daily_report(30)
        except Exception as exc:
            text = f"❌ Не удалось построить отчёт по дням: {str(exc)[:500]}"
        await callback.message.answer(text, reply_markup=menu_keyboard())
    elif key == "clubs":
        try:
            text = await club_report(30)
        except Exception as exc:
            text = f"❌ Не удалось построить отчёт по клубам: {str(exc)[:500]}"
        await callback.message.answer(text, reply_markup=menu_keyboard())
    elif key == "clients":
        async with SessionLocal() as session:
            guests = await session.scalar(select(func.count(Guest.id))) or 0
            linked = await session.scalar(select(func.count(GuestTelegram.id))) or 0
            consent = await session.scalar(select(func.count(GuestTelegram.id)).where(GuestTelegram.marketing_consent.is_(True))) or 0
        await callback.message.answer(f"👤 Клиенты\n\nВ локальном кэше: {guests}\nTelegram: {linked}\nСогласие на маркетинг: {consent}")
    await callback.answer()


@router.callback_query(F.data.startswith("analytics_admin:"))
async def analytics_admin_callback(callback: CallbackQuery):
    if not await owner(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    _, emp_id, days = callback.data.split(":")
    try:
        text = await admin_report(int(emp_id), int(days))
    except Exception as exc:
        text = f"❌ Не удалось построить отчёт: {str(exc)[:500]}"
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data.startswith("analytics_shift:"))
async def analytics_shift_callback(callback: CallbackQuery):
    if not await owner(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        text = await shift_report(int(callback.data.split(":")[1]))
    except Exception as exc:
        text = f"❌ Не удалось построить отчёт: {str(exc)[:500]}"
    await callback.message.answer(text)
    await callback.answer()
