from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func

from app.db.session import SessionLocal
from app.models import (
    Employee, Shift, Product, Club, TelegramUser, UserRole,
    ShiftCloseReport, ShiftCloseStockItem, ShiftCloseReportStatus,
)
from app.services.auth import get_access
from app.services.langame import langame_client, LangameAPIError
from app.services.audit import write_audit
from app.bot.penalties import auto_penalty_late_report

router = Router()
langame = langame_client


CLEANING_BONUS = Decimal("500.00")


def is_night_shift(shift: Shift) -> bool:
    if not shift.started_at or not shift.ended_at or shift.ended_at <= shift.started_at:
        return False
    tz = ZoneInfo("Europe/Moscow")
    start = shift.started_at.astimezone(tz)
    end = shift.ended_at.astimezone(tz)
    # Ночная смена — смена, которая пересекает полночь.
    return start.date() < end.date()


async def cleaning_required_for_shift(session, shift: Shift) -> bool:
    """Cleaning is scheduled every second night shift in a club, not per admin."""
    if not is_night_shift(shift):
        return False
    result = await session.execute(select(Shift).where(
        Shift.club_id == shift.club_id,
        Shift.status == "closed",
        Shift.started_at <= shift.started_at,
    ).order_by(Shift.started_at.asc()))
    night_shifts = [x for x in result.scalars().all() if is_night_shift(x)]
    try:
        position = next(i for i, x in enumerate(night_shifts, start=1) if x.id == shift.id)
    except StopIteration:
        return False
    return position % 2 == 0


class ShiftCloseState(StatesGroup):
    waiting_cash = State()
    waiting_cash_reason = State()
    waiting_cash_comment = State()
    waiting_stock = State()
    waiting_stock_reason = State()
    waiting_stock_comment = State()
    waiting_cleaning = State()
    waiting_cleaning_performer = State()


def _money(value) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _qty(value) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.001"))
    except (InvalidOperation, ValueError):
        raise ValueError


SHORTAGE_REASONS = {
    "damage": "Бой / порча",
    "unwritten": "Списание не оформлено",
    "count_error": "Ошибка пересчёта",
    "return": "Возврат",
    "review_reward": "Выдача администратору за отзывы гостей",
    "other": "Другое",
}

def shortage_reason_keyboard(kind: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💥 Бой / порча", callback_data=f"shift_shortage:{kind}:damage")],
        [InlineKeyboardButton(text="📝 Списание не оформлено", callback_data=f"shift_shortage:{kind}:unwritten")],
        [InlineKeyboardButton(text="🔢 Ошибка пересчёта", callback_data=f"shift_shortage:{kind}:count_error")],
        [InlineKeyboardButton(text="↩️ Возврат", callback_data=f"shift_shortage:{kind}:return")],
        [InlineKeyboardButton(text="⭐ Выдача администратору за отзывы гостей", callback_data=f"shift_shortage:{kind}:review_reward")],
        [InlineKeyboardButton(text="✏️ Другое", callback_data=f"shift_shortage:{kind}:other")],
    ])

def close_report_keyboard(report_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Открыть отчёт", callback_data=f"shift_close:view:{report_id}")],
    ])


async def _access(message: Message):
    user = await get_access(message)
    if user is None or user.role not in (UserRole.ADMIN.value, UserRole.OWNER.value):
        return None
    return user


async def _employee_open_report(session, employee_id: int):
    result = await session.execute(
        select(ShiftCloseReport, Shift, Club)
        .join(Shift, Shift.id == ShiftCloseReport.shift_id)
        .join(Club, Club.id == Shift.club_id)
        .where(
            Shift.employee_id == employee_id,
            ShiftCloseReport.status.in_([ShiftCloseReportStatus.PENDING.value, ShiftCloseReportStatus.IN_PROGRESS.value]),
        )
        .order_by(Shift.started_at.desc())
        .limit(1)
    )
    return result.first()


async def _get_or_create_report(session, shift: Shift) -> ShiftCloseReport:
    result = await session.execute(select(ShiftCloseReport).where(ShiftCloseReport.shift_id == shift.id))
    report = result.scalar_one_or_none()
    if report is None:
        report = ShiftCloseReport(
            shift_id=shift.id,
            employee_id=shift.employee_id,
            status=ShiftCloseReportStatus.PENDING.value,
        )
        session.add(report)
        await session.flush()
    return report


async def _load_langame_stock(shift: Shift, session) -> list[dict]:
    club = await session.get(Club, shift.club_id)
    if club is None:
        return []
    result = await langame.stock(club.langame_club_id)
    rows = result.get("data") or []
    items = []
    for row in rows:
        pid = row.get("id")
        if pid is None:
            continue
        product = (await session.execute(select(Product).where(Product.langame_product_id == int(pid)))).scalar_one_or_none()
        if product is None:
            product = Product(langame_product_id=int(pid), name=row.get("name") or f"Товар #{pid}")
            session.add(product)
            await session.flush()
        if not product.active:
            continue
        items.append({"product_id": product.id, "langame_product_id": int(pid), "name": product.name, "expected": _qty(row.get("count"))})
    return items




@router.message(Command("close_shift"))
async def command_close_shift(message: Message, state: FSMContext):
    await state.clear()
    user = await _access(message)
    if user is None or user.employee_id is None:
        await message.answer("⛔ Нет привязанного администратора.")
        return
    async with SessionLocal() as session:
        row = await _employee_open_report(session, user.employee_id)
        if row:
            report, shift, club = row
        else:
            result = await session.execute(select(Shift, Club).join(Club, Club.id == Shift.club_id).where(
                Shift.employee_id == user.employee_id, Shift.status == "closed"
            ).order_by(Shift.started_at.desc()).limit(1))
            found = result.first()
            if not found:
                await message.answer("📋 Закрытых смен без отчёта нет.")
                return
            shift, club = found
            report = await _get_or_create_report(session, shift)
        if report.status == ShiftCloseReportStatus.SUBMITTED.value:
            await message.answer(_format_report(report, shift, club))
            return
        if report.cash_expected is None:
            report.cash_expected = _money((shift.cash_sales or 0) - (shift.refunds_cash or 0) - (shift.collection or 0))
        report.status = ShiftCloseReportStatus.IN_PROGRESS.value
        await session.commit()
        await state.update_data(report_id=report.id, shift_id=shift.id)
    await state.set_state(ShiftCloseState.waiting_cash)
    await message.answer(
        f"🔐 <b>Отчёт по закрытию смены #{shift.langame_shift_id}</b>\n\n"
        f"💵 Расчётная наличность LANGAME: <b>{report.cash_expected:.2f} ₽</b>\n\n"
        "Введите фактическую сумму наличных в кассе:"
    )


@router.message(ShiftCloseState.waiting_cash)
async def receive_cash(message: Message, state: FSMContext):
    try:
        actual = _money(message.text.replace(" ", "").replace(",", "."))
        if actual < 0:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите сумму числом, например: 12500 или 12500.50")
        return
    data = await state.get_data()
    async with SessionLocal() as session:
        report = await session.get(ShiftCloseReport, int(data["report_id"]))
        if report is None:
            await state.clear()
            await message.answer("❌ Отчёт не найден. Начните заново: /close_shift")
            return
        report.cash_actual = actual
        report.cash_difference = _money(actual - _money(report.cash_expected))
        shift = await session.get(Shift, report.shift_id)
        shift.actual_cash = actual
        shift.cash_difference = report.cash_difference
        report.status = ShiftCloseReportStatus.IN_PROGRESS.value
        await session.commit()
        if report.cash_difference < 0:
            await state.update_data(report_id=report.id, shift_id=shift.id)
            await state.set_state(ShiftCloseState.waiting_cash_reason)
            await message.answer(
                f"🔴 Зафиксирована недостача наличных: <b>{abs(report.cash_difference):.2f} ₽</b>.\n\n"
                "Выберите причину недостачи:", reply_markup=shortage_reason_keyboard("cash")
            )
            return
    await _start_stock_check(message, state, int(data["report_id"]), int(data["shift_id"]))


async def _start_stock_check(message: Message, state: FSMContext, report_id: int, shift_id: int):
    async with SessionLocal() as session:
        report = await session.get(ShiftCloseReport, report_id)
        shift = await session.get(Shift, shift_id)
        if report is None or shift is None:
            await state.clear()
            await message.answer("❌ Отчёт не найден. Начните заново: /close_shift")
            return
        items = await _load_langame_stock(shift, session)
        existing = (await session.execute(select(ShiftCloseStockItem).where(ShiftCloseStockItem.report_id == report.id))).scalars().all()
        if not existing:
            for item in items:
                session.add(ShiftCloseStockItem(
                    report_id=report.id,
                    product_id=item["product_id"],
                    langame_quantity=item["expected"],
                ))
            await session.commit()
        result = await session.execute(
            select(ShiftCloseStockItem, Product).join(Product, Product.id == ShiftCloseStockItem.product_id)
            .where(ShiftCloseStockItem.report_id == report.id, ShiftCloseStockItem.actual_quantity.is_(None))
            .order_by(Product.name).limit(1)
        )
        next_item = result.first()
        total_items = await session.scalar(select(func.count(ShiftCloseStockItem.id)).where(ShiftCloseStockItem.report_id == report.id)) or 0
        done_items = await session.scalar(select(func.count(ShiftCloseStockItem.id)).where(ShiftCloseStockItem.report_id == report.id, ShiftCloseStockItem.actual_quantity.is_not(None))) or 0
    if next_item is None:
        await finalize_report(message, state)
        return
    item, product = next_item
    await state.update_data(current_item_id=item.id, report_id=report_id, shift_id=shift_id)
    await state.set_state(ShiftCloseState.waiting_stock)
    await message.answer(
        f"📦 <b>Проверка товара {int(done_items)+1} из {int(total_items)}</b>\n"
        f"{product.name}\n"
        f"LANGAME: <b>{item.langame_quantity:g}</b>\n\n"
        "Введите фактический остаток:"
    )


@router.callback_query(F.data.startswith("shift_shortage:"))
async def choose_shortage_reason(callback: CallbackQuery, state: FSMContext):
    _, kind, code = callback.data.split(":", 2)
    reason = SHORTAGE_REASONS.get(code)
    if not reason or kind not in ("cash", "stock"):
        await callback.answer("Некорректная причина", show_alert=True)
        return
    data = await state.get_data()
    async with SessionLocal() as session:
        if kind == "cash":
            report = await session.get(ShiftCloseReport, int(data["report_id"]))
            if report is None:
                await callback.answer("Отчёт не найден", show_alert=True); return
            report.cash_shortage_reason = reason
            await session.commit()
            await state.set_state(ShiftCloseState.waiting_cash_comment)
            prompt = "Причина сохранена. Теперь укажите комментарий к недостаче (что произошло)."
        else:
            item = await session.get(ShiftCloseStockItem, int(data["current_item_id"]))
            if item is None:
                await callback.answer("Позиция не найдена", show_alert=True); return
            item.shortage_reason = reason
            await session.commit()
            await state.set_state(ShiftCloseState.waiting_stock_comment)
            prompt = "Причина сохранена. Теперь укажите комментарий к недостаче (что произошло)."
    await callback.answer("Причина сохранена")
    await callback.message.answer("📝 " + prompt)

@router.message(ShiftCloseState.waiting_cash_comment)
async def receive_cash_comment(message: Message, state: FSMContext):
    comment = (message.text or "").strip()
    if not comment:
        await message.answer("❌ Комментарий не может быть пустым. Укажите причину недостачи.")
        return
    data = await state.get_data()
    async with SessionLocal() as session:
        report = await session.get(ShiftCloseReport, int(data["report_id"]))
        if report is None:
            await state.clear()
            await message.answer("❌ Отчёт не найден. Начните заново: /close_shift")
            return
        report.cash_comment = comment[:4000]
        await session.commit()
    await _start_stock_check(message, state, int(data["report_id"]), int(data["shift_id"]))


@router.message(ShiftCloseState.waiting_stock)
async def receive_stock(message: Message, state: FSMContext):
    try:
        actual = _qty(message.text.replace(" ", "").replace(",", "."))
        if actual < 0:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите количество числом, например: 12 или 12.5")
        return
    data = await state.get_data()
    async with SessionLocal() as session:
        item = await session.get(ShiftCloseStockItem, int(data["current_item_id"]))
        if item is None:
            await state.clear()
            await message.answer("❌ Позиция не найдена. Начните заново: /close_shift")
            return
        item.actual_quantity = actual
        item.difference = actual - item.langame_quantity
        await session.commit()
        if item.difference < 0:
            await state.update_data(current_item_id=item.id, report_id=item.report_id, shift_id=data.get("shift_id"))
            await state.set_state(ShiftCloseState.waiting_stock_reason)
            await message.answer(
                f"🔴 Недостача <b>{abs(item.difference):g}</b> по товару <b>{(await session.get(Product, item.product_id)).name}</b>.\n\n"
                "Выберите причину недостачи:", reply_markup=shortage_reason_keyboard("stock")
            )
            return
    await _continue_stock_check(message, state, item.report_id)


@router.message(ShiftCloseState.waiting_stock_comment)
async def receive_stock_comment(message: Message, state: FSMContext):
    comment = (message.text or "").strip()
    if not comment:
        await message.answer("❌ Комментарий не может быть пустым. Укажите причину недостачи.")
        return
    data = await state.get_data()
    async with SessionLocal() as session:
        item = await session.get(ShiftCloseStockItem, int(data["current_item_id"]))
        if item is None:
            await state.clear()
            await message.answer("❌ Позиция не найдена. Начните заново: /close_shift")
            return
        item.comment = comment[:4000]
        await session.commit()
    await _continue_stock_check(message, state, int(data["report_id"]))


async def _continue_stock_check(message: Message, state: FSMContext, report_id: int):
    async with SessionLocal() as session:
        result = await session.execute(
            select(ShiftCloseStockItem, Product).join(Product, Product.id == ShiftCloseStockItem.product_id)
            .where(ShiftCloseStockItem.report_id == report_id, ShiftCloseStockItem.actual_quantity.is_(None))
            .order_by(Product.name).limit(1)
        )
        next_item = result.first()
        total = await session.scalar(select(func.count(ShiftCloseStockItem.id)).where(ShiftCloseStockItem.report_id == report_id)) or 0
        done = await session.scalar(select(func.count(ShiftCloseStockItem.id)).where(ShiftCloseStockItem.report_id == report_id, ShiftCloseStockItem.actual_quantity.is_not(None))) or 0
    if next_item is None:
        await finalize_report(message, state)
        return
    next_obj, product = next_item
    await state.update_data(current_item_id=next_obj.id, report_id=report_id)
    await state.set_state(ShiftCloseState.waiting_stock)
    await message.answer(
        f"📦 <b>Следующий товар: {int(done)+1} из {int(total)}</b>\n"
        f"{product.name}\nLANGAME: <b>{next_obj.langame_quantity:g}</b>\n\n"
        "Введите фактический остаток:"
    )


async def finalize_report(message: Message, state: FSMContext):
    data = await state.get_data()
    async with SessionLocal() as session:
        report = await session.get(ShiftCloseReport, int(data["report_id"]))
        if report is None:
            await state.clear(); return
        result = await session.execute(select(ShiftCloseStockItem).where(ShiftCloseStockItem.report_id == report.id))
        items = result.scalars().all()
        discrepancies = [x for x in items if x.difference and x.difference != 0]
        report.stock_items_count = len(items)
        report.stock_discrepancies_count = len(discrepancies)
        shift = await session.get(Shift, report.shift_id)
        if shift:
            shift.actual_cash = report.cash_actual
            shift.cash_difference = report.cash_difference
        if shift and await cleaning_required_for_shift(session, shift) and report.cleaning_confirmed_at is None:
            await session.commit()
            await state.set_state(ShiftCloseState.waiting_cleaning)
            await message.answer(
                "🧹 <b>Уборка помещения</b>\n\n"
                "Уборка выполняется через одну ночную смену. Она не закреплена за конкретным администратором.\n"
                f"При отсутствии пропусков уборки за весь календарный месяц будет начислен единоразовый бонус <b>{CLEANING_BONUS:.0f} ₽</b>.\n\n"
                "Подтвердите, что уборка выполнена:",
                reply_markup=cleaning_keyboard(),
            )
            return
        await _submit_report(session, report, shift, message.from_user.id)
        await session.commit()
        club = await session.get(Club, shift.club_id) if shift else None
        text = _format_report(report, shift, club)
    await state.clear()
    await message.answer("✅ <b>Отчёт о закрытии смены принят.</b>\n\n" + text)


def cleaning_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧹 Уборка выполнена", callback_data="shift_cleaning:done")],
    ])


async def _submit_report(session, report, shift, actor_telegram_id: int):
    report.status = ShiftCloseReportStatus.SUBMITTED.value
    report.submitted_at = datetime.now(timezone.utc)
    await auto_penalty_late_report(report, report.employee_id, session)
    await write_audit(session, actor_telegram_id=actor_telegram_id, actor_employee_id=report.employee_id,
                      action="submit_shift_close_report", entity_type="shift_close_report", entity_id=str(report.id),
                      payload={"shift_id": report.shift_id, "cash_difference": str(report.cash_difference),
                               "stock_discrepancies": int(report.stock_discrepancies_count or 0),
                               "cleaning_bonus": "monthly_500_if_no_missed_cleanings"})


@router.callback_query(F.data == "shift_cleaning:done")
async def confirm_cleaning(callback: CallbackQuery, state: FSMContext):
    user = await _access(callback.message)
    if user is None or user.employee_id is None:
        await callback.answer("Нет доступа", show_alert=True)
        return
    data = await state.get_data()
    report_id = data.get("report_id")
    if not report_id:
        await callback.answer("Отчёт не найден", show_alert=True)
        return
    async with SessionLocal() as session:
        report = await session.get(ShiftCloseReport, int(report_id))
        if report is None or report.employee_id != user.employee_id:
            await callback.answer("Отчёт не найден", show_alert=True)
            return
        shift = await session.get(Shift, report.shift_id)
        if shift is None or not await cleaning_required_for_shift(session, shift):
            await callback.answer("Для этой смены уборка не запланирована", show_alert=True)
            return
        await state.update_data(report_id=report.id, shift_id=shift.id)
        await state.set_state(ShiftCloseState.waiting_cleaning_performer)
    await callback.answer()
    await callback.message.answer("👤 Укажите, кто фактически выполнил уборку (ФИО или имя). Это может быть не администратор смены:")


@router.message(ShiftCloseState.waiting_cleaning_performer)
async def receive_cleaning_performer(message: Message, state: FSMContext):
    performer = (message.text or "").strip()
    if not performer:
        await message.answer("❌ Укажите имя человека, который выполнил уборку.")
        return
    data = await state.get_data()
    async with SessionLocal() as session:
        report = await session.get(ShiftCloseReport, int(data["report_id"]))
        if report is None:
            await state.clear(); await message.answer("❌ Отчёт не найден."); return
        shift = await session.get(Shift, report.shift_id)
        if shift is None or not await cleaning_required_for_shift(session, shift):
            await state.clear(); await message.answer("❌ Для этой смены уборка не запланирована."); return
        report.cleaning_confirmed_at = datetime.now(timezone.utc)
        report.cleaning_performed_by = performer[:255]
        report.cleaning_bonus_amount = Decimal("0.00")
        await _submit_report(session, report, shift, message.from_user.id)
        await session.commit()
        club = await session.get(Club, shift.club_id)
        text = _format_report(report, shift, club)
    await state.clear()
    await message.answer("✅ <b>Уборка зафиксирована.</b>\n\n" + text)


def _format_report(report, shift, club) -> str:
    cash_diff = _money(report.cash_difference)
    cash_flag = "🟢" if cash_diff == 0 else "🔴"
    stock_flag = "🟢" if (report.stock_discrepancies_count or 0) == 0 else "🔴"
    return (
        f"📋 <b>Отчёт смены #{shift.langame_shift_id}</b>\n"
        f"🏢 {club.name if club else '—'}\n"
        f"💵 LANGAME: {report.cash_expected:.2f} ₽\n"
        f"💵 Факт: {report.cash_actual:.2f} ₽\n"
        f"{cash_flag} Разница: <b>{cash_diff:.2f} ₽</b>\n"
        f"🏷 Причина недостачи по кассе: {report.cash_shortage_reason or '—'}\n"
        f"📝 Комментарий по кассе: {report.cash_comment or '—'}\n"
        f"🧹 Уборка: {"выполнена" if report.cleaning_confirmed_at else "—"}\n"
        f"👤 Выполнил: {report.cleaning_performed_by or "—"}\n"
        f"🧾 Месячный бонус за уборку: рассчитывается по итогам календарного месяца\n"
        f"📦 Проверено товаров: {report.stock_items_count or 0}\n"
        f"{stock_flag} Расхождений: <b>{report.stock_discrepancies_count or 0}</b>\n"
        f"Статус: {report.status}"
    )


@router.callback_query(F.data.startswith("shift_close:view:"))
async def view_close_report(callback: CallbackQuery):
    user = await get_access(callback.message)
    if user is None:
        await callback.answer("Нет доступа", show_alert=True); return
    report_id = int(callback.data.rsplit(":", 1)[1])
    async with SessionLocal() as session:
        report = await session.get(ShiftCloseReport, report_id)
        if report is None:
            await callback.answer("Не найден", show_alert=True); return
        shift = await session.get(Shift, report.shift_id)
        club = await session.get(Club, shift.club_id)
        if user.role != UserRole.OWNER.value and shift.employee_id != user.employee_id:
            await callback.answer("Нет доступа", show_alert=True); return
        items = (await session.execute(select(ShiftCloseStockItem, Product).join(Product, Product.id == ShiftCloseStockItem.product_id).where(ShiftCloseStockItem.report_id == report.id).order_by(Product.name))).all()
    lines = [_format_report(report, shift, club), "", "📦 <b>Товары с расхождениями:</b>"]
    bad = [f"• {p.name}: LANGAME {i.langame_quantity:g} → факт {i.actual_quantity:g} ({i.difference:+g})" + (f" — {i.shortage_reason}" if i.shortage_reason else "") + (f" — {i.comment}" if i.comment else "") for i,p in items if i.difference]
    lines.extend(bad or ["• Нет расхождений"])
    await callback.message.answer("\n".join(lines))
    await callback.answer()


async def notify_pending_shift_reports(bot) -> None:
    """Create close reports for newly closed shifts and remind linked admins."""
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        result = await session.execute(select(Shift).where(
            Shift.status == "closed",
            Shift.employee_id.is_not(None),
            Shift.ended_at >= now - timedelta(hours=48),
        ))
        shifts = result.scalars().all()
        targets = []
        for shift in shifts:
            report = await _get_or_create_report(session, shift)
            if report.status == ShiftCloseReportStatus.SUBMITTED.value:
                continue
            if report.first_notified_at is not None and now - report.first_notified_at >= timedelta(minutes=30):
                await auto_penalty_late_report(report, shift.employee_id, session)
            if report.first_notified_at is None:
                report.first_notified_at = now
                report.last_notified_at = now
                targets.append((shift, report, "first"))
            elif report.last_notified_at is None or now - report.last_notified_at >= timedelta(minutes=30):
                # Keep reminders bounded to 24h; after that it becomes an owner attention item.
                if report.first_notified_at and now - report.first_notified_at <= timedelta(hours=24):
                    targets.append((shift, report, "reminder"))
                report.last_notified_at = now
        await session.commit()
        for shift, report, kind in targets:
            tg_rows = (await session.execute(select(TelegramUser).where(
                TelegramUser.employee_id == shift.employee_id,
                TelegramUser.active.is_(True),
            ))).scalars().all()
            for tg in tg_rows:
                try:
                    prefix = "🔔 Напоминание" if kind == "reminder" else "🔔 Требуется"
                    await bot.send_message(
                        tg.telegram_id,
                        f"{prefix} закрыть отчёт по смене #{shift.langame_shift_id}.\n\n"
                        f"После закрытия смены необходимо пересчитать наличные и проверить остатки всех товаров.\n"
                        f"Отчёт: /close_shift",
                        reply_markup=close_report_keyboard(report.id),
                    )
                except Exception:
                    pass


async def shift_close_scheduler(bot):
    while True:
        try:
            # Reuse the authoritative LANGAME shift sync before checking closures.
            from app.bot.salary import sync_shifts_data
            await sync_shifts_data()
            await notify_pending_shift_reports(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(60)


@router.message(F.text == "🔐 Закрыть смену")
async def close_shift_button(message: Message, state: FSMContext):
    await command_close_shift(message, state)
