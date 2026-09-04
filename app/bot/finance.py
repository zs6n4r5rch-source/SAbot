from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Employee, SalaryPeriod, Shift, TelegramUser, UserRole
from app.bot.analytics import sales_rows

router = Router()


def finance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 7 дней", callback_data="finance:7"), InlineKeyboardButton(text="📅 30 дней", callback_data="finance:30")],
        [InlineKeyboardButton(text="📅 Этот месяц", callback_data="finance:month")],
        [InlineKeyboardButton(text="👥 По администраторам", callback_data="finance:admins")],
    ])


async def is_owner(uid: int | None) -> bool:
    if uid is None:
        return False
    async with SessionLocal() as session:
        user = (await session.execute(select(TelegramUser).where(TelegramUser.telegram_id == uid))).scalar_one_or_none()
        return bool(user and user.active and user.role == UserRole.OWNER.value)


def period(kind: str):
    now = datetime.now(timezone.utc)
    if kind == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now, "текущий месяц"
    days = int(kind)
    return now - timedelta(days=days), now, f"последние {days} дней"


async def shift_finance(start: datetime, end: datetime):
    async with SessionLocal() as session:
        rows = (await session.execute(select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.started_at >= start, Shift.started_at <= end))).all()
    cash = card = mobile = refunds_cash = refunds_card = collection = Decimal("0")
    hours = Decimal("0")
    by_employee: dict[int, dict] = {}
    for sh, emp in rows:
        cash += Decimal(str(sh.cash_sales or 0)); card += Decimal(str(sh.card_sales or 0)); mobile += Decimal(str(sh.mobile_sales or 0))
        refunds_cash += Decimal(str(sh.refunds_cash or 0)); refunds_card += Decimal(str(sh.refunds_card or 0)); collection += Decimal(str(sh.collection or 0))
        if sh.ended_at and sh.ended_at > sh.started_at:
            h = Decimal(str((sh.ended_at - sh.started_at).total_seconds())) / Decimal("3600")
            hours += h
        else:
            h = Decimal("0")
        if emp:
            st = by_employee.setdefault(emp.id, {"name": emp.full_name or f"Администратор #{emp.id}", "hours": Decimal("0"), "shifts": 0, "cash": Decimal("0"), "card": Decimal("0"), "mobile": Decimal("0"), "refunds": Decimal("0"), "collection": Decimal("0")})
            st["hours"] += h; st["shifts"] += 1; st["cash"] += Decimal(str(sh.cash_sales or 0)); st["card"] += Decimal(str(sh.card_sales or 0)); st["mobile"] += Decimal(str(sh.mobile_sales or 0)); st["refunds"] += Decimal(str(sh.refunds_cash or 0)) + Decimal(str(sh.refunds_card or 0)); st["collection"] += Decimal(str(sh.collection or 0))
    return rows, {"cash": cash, "card": card, "mobile": mobile, "refunds_cash": refunds_cash, "refunds_card": refunds_card, "collection": collection, "hours": hours, "by_employee": by_employee}


async def finance_report(kind: str) -> str:
    start, end, label = period(kind)
    _, f = await shift_finance(start, end)
    sales, units, _ = await _product_sales(start, end)
    gross_channels = f["cash"] + f["card"] + f["mobile"]
    refunds = f["refunds_cash"] + f["refunds_card"]
    net_channels = gross_channels - refunds - f["collection"]
    per_hour = sales / f["hours"] if f["hours"] > 0 else Decimal("0")
    async with SessionLocal() as session:
        salary_accrued = await session.scalar(select(func.coalesce(func.sum(SalaryPeriod.total_amount), 0)).where(SalaryPeriod.date_from <= end.date(), SalaryPeriod.date_to >= start.date())) or 0
    return (f"💰 <b>Финансовый контроль — {label}</b>\n\n"
            f"📈 Продажи бара и снеков: <b>{sales:.2f} ₽</b> · {units:g} ед.\n"
            f"⏱ Часы смен: <b>{f['hours']:.1f}</b>\n"
            f"📊 Продажи/час: <b>{per_hour:.2f} ₽</b>\n\n"
            f"💵 Наличные по сменам: <b>{f['cash']:.2f} ₽</b>\n"
            f"💳 Безналичные: <b>{f['card']:.2f} ₽</b>\n"
            f"📱 Мобильные платежи: <b>{f['mobile']:.2f} ₽</b>\n"
            f"↩️ Возвраты: <b>{refunds:.2f} ₽</b>\n"
            f"🏦 Инкассация: <b>{f['collection']:.2f} ₽</b>\n"
            f"💰 Остаток потоков после возвратов/инкассации: <b>{net_channels:.2f} ₽</b>\n\n"
            f"💼 Начислено в зарплатных периодах: <b>{Decimal(str(salary_accrued)):.2f} ₽</b>\n\n"
            "ℹ️ Кассовая разница здесь не рассчитывается автоматически: LANGAME не предоставляет фактическую сумму наличных для записи в эту систему."
           )


async def _product_sales(start, end):
    rows = await sales_rows(start, end)
    total = units = Decimal("0")
    for row in rows:
        if int(row.get("cancel", 0) or 0) == 1:
            continue
        try:
            q = Decimal(str(row.get("count", 0) or 0)); total += Decimal(str(row.get("price_sale", 0) or 0)) * q; units += q
        except Exception:
            pass
    return total, units, rows


async def admin_finance_report() -> str:
    start, end, label = period("30")
    _, f = await shift_finance(start, end)
    ranked = sorted(f["by_employee"].values(), key=lambda x: (x["cash"] + x["card"] + x["mobile"] - x["refunds"]), reverse=True)
    lines = [f"👥 <b>Финансы по администраторам — {label}</b>", ""]
    for i, x in enumerate(ranked[:20], 1):
        net = x["cash"] + x["card"] + x["mobile"] - x["refunds"]
        per_hour = net / x["hours"] if x["hours"] > 0 else Decimal("0")
        lines.append(f"{i}. <b>{x['name']}</b>\n   Смен: {x['shifts']} · {x['hours']:.1f} ч · поток: {net:.2f} ₽ · {per_hour:.2f} ₽/ч")
    return "\n".join(lines) if len(lines) > 2 else "👥 За последние 30 дней финансовых данных по администраторам нет."


@router.message(F.text == "💰 Финансы")
async def finance_button(message: Message):
    if not await is_owner(message.from_user.id if message.from_user else None):
        await message.answer("⛔ Доступ только для владельца.")
        return
    await message.answer(await finance_report("7"), reply_markup=finance_keyboard())


@router.callback_query(F.data.startswith("finance:"))
async def finance_callback(callback: CallbackQuery):
    if not await is_owner(callback.from_user.id if callback.from_user else None):
        await callback.answer("Нет доступа", show_alert=True); return
    key = callback.data.split(":", 1)[1]
    if key == "admins":
        text = await admin_finance_report()
    else:
        try: text = await finance_report(key)
        except Exception as exc: text = f"❌ Не удалось построить финансовый отчёт: {str(exc)[:500]}"
    await callback.message.answer(text, reply_markup=finance_keyboard())
    await callback.answer()
