from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import (
    Discrepancy, Employee, InventoryOperation, SalaryPeriod, Shift,
    TelegramUser, UserRole, Writeoff, WriteoffItem, WriteoffStatus,
)
from app.bot.analytics import sales_rows

router = Router()


def _period(days: int = 30):
    end = datetime.now(timezone.utc)
    return end - timedelta(days=days), end


async def _is_owner(uid: int | None) -> bool:
    if uid is None:
        return False
    async with SessionLocal() as session:
        user = (await session.execute(select(TelegramUser).where(TelegramUser.telegram_id == uid))).scalar_one_or_none()
        return bool(user and user.active and user.role == UserRole.OWNER.value)


def _kb(days: int = 30, rows=None):
    buttons = [[InlineKeyboardButton(text="📅 7 дней", callback_data="integrity:7"), InlineKeyboardButton(text="📅 30 дней", callback_data="integrity:30")]]
    for x in (rows or [])[:5]:
        e = x["employee"]
        buttons.append([InlineKeyboardButton(
            text=f"📁 {(e.full_name or f'Администратор #{e.id}')[:24]} · {x['score']}/100",
            callback_data=f"integrity:dossier:{e.id}:{days}"
        )])
    buttons += [
        [InlineKeyboardButton(text="👥 Администраторы", callback_data="aprofiles:list")],
        [InlineKeyboardButton(text="⬅️ Требует внимания", callback_data="dashboard:attention")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _rows(days: int = 30):
    start, end = _period(days)
    async with SessionLocal() as session:
        employees = (await session.execute(select(Employee).where(Employee.active.is_(True)).order_by(Employee.full_name.asc()))).scalars().all()
        shifts = (await session.execute(select(Shift).where(Shift.employee_id.is_not(None), Shift.started_at >= start, Shift.started_at <= end))).scalars().all()
        discrepancies = (await session.execute(select(Discrepancy).where(Discrepancy.employee_id.is_not(None), Discrepancy.created_at >= start, Discrepancy.created_at <= end))).scalars().all()
        writeoffs = (await session.execute(select(Writeoff, WriteoffItem).join(WriteoffItem, WriteoffItem.writeoff_id == Writeoff.id).where(
            Writeoff.employee_id.is_not(None), Writeoff.created_at >= start, Writeoff.created_at <= end,
            Writeoff.status == WriteoffStatus.APPROVED.value))).all()
        audit_ops = (await session.execute(select(InventoryOperation).where(
            InventoryOperation.employee_id.is_not(None), InventoryOperation.created_at >= start, InventoryOperation.created_at <= end,
            InventoryOperation.operation_type.in_(["manual_adjustment", "inventory_adjustment"])))) .scalars().all()

    shift_map = {int(s.langame_shift_id): s for s in shifts}
    stats = {e.id: {
        "employee": e, "shifts": 0, "hours": Decimal("0"), "sales": Decimal("0"), "cancel_rows": 0,
        "sale_rows": 0, "writeoff_units": Decimal("0"), "writeoffs": 0,
        "disc_count": 0, "disc_amount": Decimal("0"), "manual_adjustments": 0,
        "cash_diff": Decimal("0"), "reasons": [], "score": 0,
    } for e in employees}

    for s in shifts:
        x = stats.get(s.employee_id)
        if not x:
            continue
        x["shifts"] += 1
        if s.ended_at and s.ended_at > s.started_at:
            x["hours"] += Decimal(str((s.ended_at - s.started_at).total_seconds())) / Decimal("3600")
        if s.cash_difference is not None:
            x["cash_diff"] += Decimal(str(s.cash_difference))

    for d in discrepancies:
        x = stats.get(d.employee_id)
        if not x:
            continue
        x["disc_count"] += 1
        x["disc_amount"] += abs(Decimal(str(d.amount_difference or 0)))

    for w, item in writeoffs:
        x = stats.get(w.employee_id)
        if not x:
            continue
        x["writeoffs"] += 1
        x["writeoff_units"] += Decimal(str(item.quantity or 0))

    for op in audit_ops:
        x = stats.get(op.employee_id)
        if x:
            x["manual_adjustments"] += 1

    try:
        for row in await sales_rows(start, end):
            sid = row.get("working_shift_id")
            if sid is None or int(sid) not in shift_map:
                continue
            x = stats.get(shift_map[int(sid)].employee_id)
            if not x:
                continue
            x["sale_rows"] += 1
            if int(row.get("cancel", 0) or 0) == 1:
                x["cancel_rows"] += 1
                continue
            try:
                x["sales"] += Decimal(str(row.get("price_sale", 0) or 0)) * Decimal(str(row.get("count", 0) or 0))
            except Exception:
                continue
    except Exception:
        pass

    active = list(stats.values())
    cancel_rates = [Decimal(x["cancel_rows"]) / Decimal(x["sale_rows"]) for x in active if x["sale_rows"] > 0]
    writeoff_rates = [x["writeoff_units"] / Decimal(x["shifts"]) for x in active if x["shifts"] > 0]
    median_cancel = sorted(cancel_rates)[len(cancel_rates) // 2] if cancel_rates else Decimal("0")
    median_writeoff = sorted(writeoff_rates)[len(writeoff_rates) // 2] if writeoff_rates else Decimal("0")

    for x in active:
        reasons = []
        score = 0
        cancel_rate = Decimal(x["cancel_rows"]) / Decimal(x["sale_rows"]) if x["sale_rows"] else Decimal("0")
        writeoff_rate = x["writeoff_units"] / Decimal(x["shifts"]) if x["shifts"] else Decimal("0")
        if x["disc_count"] >= 2:
            score += 35; reasons.append(f"{x['disc_count']} расхождений")
        elif x["disc_count"] == 1:
            score += 15; reasons.append("есть расхождение")
        if x["disc_amount"] >= Decimal("500"):
            score += 20; reasons.append(f"расхождения на {x['disc_amount']:.0f} ₽")
        if x["writeoffs"] >= 3:
            score += 15; reasons.append(f"{x['writeoffs']} одобренных списания")
        if x["shifts"] and x["writeoff_units"] > 0 and (median_writeoff == 0 and writeoff_rate >= 1 or median_writeoff > 0 and writeoff_rate >= median_writeoff * 2 and writeoff_rate >= 1):
            score += 15; reasons.append("списания заметно выше медианы")
        if x["sale_rows"] >= 20 and cancel_rate >= Decimal("0.05"):
            score += 20; reasons.append(f"отмены продаж {cancel_rate * 100:.1f}%")
        if x["sale_rows"] >= 20 and median_cancel > 0 and cancel_rate >= median_cancel * 2 and cancel_rate >= Decimal("0.03"):
            score += 15; reasons.append("доля отмен выше медианы коллег")
        if x["manual_adjustments"] >= 2:
            score += 10; reasons.append(f"{x['manual_adjustments']} ручных корректировки")
        if x["cash_diff"] != 0:
            score += 10; reasons.append(f"разница по кассе {x['cash_diff']:.0f} ₽")
        x["cancel_rate"] = cancel_rate
        x["writeoff_rate"] = writeoff_rate
        x["score"] = min(score, 100)
        x["reasons"] = reasons
    return sorted(active, key=lambda x: (x["score"], x["disc_amount"], x["cancel_rate"]), reverse=True)


async def _risk_index_rows(days: int = 30):
    start, end = _period(days)
    async with SessionLocal() as session:
        employees = (await session.execute(select(Employee).where(Employee.active.is_(True)).order_by(Employee.full_name.asc()))).scalars().all()
        shifts = (await session.execute(select(Shift).where(Shift.employee_id.is_not(None), Shift.started_at >= start, Shift.started_at <= end))).scalars().all()
        writeoffs = (await session.execute(select(Writeoff, WriteoffItem).join(WriteoffItem, WriteoffItem.writeoff_id == Writeoff.id).where(Writeoff.employee_id.is_not(None), Writeoff.shift_id.is_not(None), Writeoff.created_at >= start, Writeoff.created_at <= end, Writeoff.status == WriteoffStatus.APPROVED.value))).all()
        discrepancies = (await session.execute(select(Discrepancy).where(Discrepancy.employee_id.is_not(None), Discrepancy.shift_id.is_not(None), Discrepancy.created_at >= start, Discrepancy.created_at <= end))).scalars().all()
    by_shift = {int(sh.id): {"shift": sh, "sales_rows": 0, "cancel_rows": 0, "sales": Decimal("0"), "cancel_amount": Decimal("0"), "writeoff_units": Decimal("0"), "writeoffs": 0, "disc_amount": Decimal("0"), "discs": 0} for sh in shifts}
    try:
        for row in await sales_rows(start, end):
            sid = row.get("working_shift_id")
            if sid is None: continue
            match = next((x for x in by_shift.values() if int(x["shift"].langame_shift_id) == int(sid)), None)
            if not match: continue
            qty = Decimal(str(row.get("count", 0) or 0)); amount = Decimal(str(row.get("price_sale", 0) or 0)) * qty
            match["sales_rows"] += 1
            if int(row.get("cancel", 0) or 0) == 1:
                match["cancel_rows"] += 1; match["cancel_amount"] += amount
            else: match["sales"] += amount
    except Exception:
        pass
    for w, item in writeoffs:
        x = by_shift.get(int(w.shift_id))
        if x: x["writeoffs"] += 1; x["writeoff_units"] += Decimal(str(item.quantity or 0))
    for d in discrepancies:
        x = by_shift.get(int(d.shift_id))
        if x: x["discs"] += 1; x["disc_amount"] += abs(Decimal(str(d.amount_difference or 0)))
    try: baseline_rows = await sales_rows(start - timedelta(days=90), end)
    except Exception: baseline_rows = []
    sales_by_shift_baseline = {}
    for r in baseline_rows:
        sid = r.get("working_shift_id")
        if sid is None: continue
        key = int(sid); total, cancels = sales_by_shift_baseline.get(key, (0, 0)); sales_by_shift_baseline[key] = (total + 1, cancels + int(r.get("cancel", 0) or 0))
    results = []
    async with SessionLocal() as session:
        for e in employees:
            emp_shifts = [x for x in shifts if x.employee_id == e.id]
            prior = (await session.execute(select(Shift).where(Shift.employee_id == e.id, Shift.status == "closed", Shift.started_at < start, Shift.started_at >= start - timedelta(days=90)).order_by(Shift.started_at.desc()).limit(30))).scalars().all()
            prior_metrics = []
            for ps in prior:
                total, cancels = sales_by_shift_baseline.get(int(ps.langame_shift_id), (0, 0)); prior_metrics.append((Decimal(cancels) / Decimal(total) * 100) if total else Decimal("0"))
            linked = []
            for x in emp_shifts:
                m = by_shift.get(int(x.id))
                if not m: continue
                patterns = []
                if m["cancel_rows"] >= 3 and m["writeoff_units"] > 0: patterns.append("отмены + списание")
                if m["cancel_rows"] >= 3 and m["disc_amount"] > 0: patterns.append("отмены + расхождение")
                if m["writeoff_units"] > 0 and m["disc_amount"] > 0: patterns.append("списание + расхождение")
                if abs(Decimal(str(x.cash_difference or 0))) > 0 and m["disc_amount"] > 0: patterns.append("касса + расхождение")
                if patterns: linked.append((x, m, patterns))
            score = 0; reasons = []; pattern_shifts = set()
            for sh, m, patterns in linked:
                pattern_shifts.add(sh.id)
                score += 20 if len(patterns) >= 2 else 8
                reasons.append(f"смена #{sh.langame_shift_id}: {len(patterns)} связанных сигнала" if len(patterns) >= 2 else f"смена #{sh.langame_shift_id}: {patterns[0]}")
            current_rates = []
            for x in emp_shifts:
                m = by_shift.get(int(x.id))
                if m and m["sales_rows"]: current_rates.append((x, Decimal(m["cancel_rows"]) / Decimal(m["sales_rows"]) * 100))
            if len(prior_metrics) >= 5 and prior_metrics:
                med = _median(prior_metrics) or Decimal("0")
                high = [(sh, rate) for sh, rate in current_rates if (rate >= med * 2 and rate >= Decimal("5")) or (med == 0 and rate >= Decimal("5"))]
                if high: score += min(25, 10 + 5 * min(len(high), 3)); reasons.append(f"отмены выше личной нормы в {len(high)} сменах")
            disc_shifts = {int(d.shift_id) for d in discrepancies if d.employee_id == e.id and d.shift_id is not None}
            wo_shifts = {int(w.shift_id) for w, _ in writeoffs if w.employee_id == e.id and w.shift_id is not None}
            if len(disc_shifts) >= 2: score += 15; reasons.append(f"расхождения в {len(disc_shifts)} сменах")
            if len(wo_shifts) >= 3: score += 10; reasons.append(f"списания в {len(wo_shifts)} сменах")
            cash_total = sum((abs(Decimal(str(x.cash_difference or 0))) for x in emp_shifts), Decimal("0"))
            if cash_total >= Decimal("500"): score += 10; reasons.append(f"суммарная разница по кассе {cash_total:.0f} ₽")
            results.append({"employee": e, "score": min(score, 100), "reasons": reasons[:5], "pattern_shifts": len(pattern_shifts), "linked_events": len(linked), "shifts": len(emp_shifts)})
    return sorted(results, key=lambda x: (x["score"], x["pattern_shifts"], x["linked_events"]), reverse=True)


def _median(values):
    if not values: return Decimal("0")
    values = sorted(values)
    n = len(values); mid = n // 2
    return values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2


def _level(score: int) -> str:
    if score >= 60: return "🔴 Высокий риск"
    if score >= 30: return "🟡 Нужна проверка"
    return "🟢 Низкий риск"


async def integrity_text(days: int = 30) -> str:
    rows = await _rows(days)
    suspicious = [x for x in rows if x["score"] >= 30]
    lines = [f"🔎 <b>Контроль добросовестности — {days} дней</b>", "", "Оценка ищет повторяющиеся аномалии: расхождения, списания, отмены продаж и ручные корректировки.", "⚠️ Это не доказательство нарушения — перед решением нужна проверка первичных данных.", ""]
    if not suspicious:
        lines.append("✅ Явных повторяющихся аномалий не найдено.")
        return "\n".join(lines)
    for i, x in enumerate(suspicious[:10], 1):
        e = x["employee"]
        lines.append(f"{i}. <b>{e.full_name or f'Администратор #{e.id}'}</b> — {_level(x['score'])} · {x['score']}/100")
        lines.append("   " + "; ".join(x["reasons"][:4]))
        lines.append(f"   смен {x['shifts']} · продажи {x['sales']:.0f} ₽ · отмены {x['cancel_rate']*100:.1f}%")
    return "\n".join(lines)


@router.message(F.text == "🔎 Контроль администраторов")
async def integrity_button(message: Message):
    if not await _is_owner(message.from_user.id if message.from_user else None):
        await message.answer("⛔ Только владелец.")
        return
    rows = await _rows(30)
    await message.answer(await integrity_text(30), reply_markup=_kb(30, [x for x in rows if x["score"] >= 30]))


@router.callback_query(F.data.startswith("integrity:"))
async def integrity_callback(call: CallbackQuery):
    if not await _is_owner(call.from_user.id if call.from_user else None):
        await call.answer("Нет доступа", show_alert=True)
        return
    days = int(call.data.split(":", 1)[1])
    rows = await _rows(days)
    await call.message.edit_text(await integrity_text(days), reply_markup=_kb(days, [x for x in rows if x["score"] >= 30]))
    await call.answer()
