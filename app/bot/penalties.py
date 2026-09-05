from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User
from sqlalchemy import select, func

from app.db.session import SessionLocal
from app.bot.keyboards import admins_menu
from app.models import Employee, SalaryViolation, TelegramUser, UserRole, Shift
from app.services.audit import write_audit
from app.services.auth import get_access

router = Router()

RULES = [
    ("smoking", "🚬 Курение вне специально отведённых мест", Decimal("500"), False, False),
    ("dirty_area", "🧹 Грязь/пыль/еда на столах или вещи на столе администратора", Decimal("500"), True, False),
    ("guest_drinks", "🥤 Свои напитки гостя без пробкового сбора", Decimal("500"), False, False),
    ("uniform", "👕 Мятая/нет формы/неопрятный внешний вид", Decimal("500"), False, False),
    ("entrance_trash", "📦 Коробки/упаковка/мусор у входа/ресепшена", Decimal("500"), False, False),
    ("late_request", "🧻 Поздняя заявка на лампы/туалетную бумагу/уборку и т.п.", Decimal("500"), True, False),
    ("off_schedule_open", "🔓 Открытие смены не по графику", Decimal("1000"), False, False),
    ("cash_discipline", "💵 Нарушение кассовой дисциплины", Decimal("500"), False, False),
    ("strangers", "🚷 Посторонние в помещении вне рабочего времени", Decimal("1000"), False, False),
    ("commercial_break", "⛔ Перерыв в коммерческой деятельности в рабочее время (кроме обеда)", Decimal("1000"), False, False),
    ("secret_shopper", "🕵️ Провал тайного покупателя", Decimal("500"), False, False),
    ("receipt_money", "🧾 Деньги не внесены при выданном чеке", Decimal("0"), False, True),
    ("discount_abuse", "🏷 Присвоение/злоупотребление через скидки, неверную цену и т.п.", Decimal("0"), False, True),
    ("insult_sa", "⚠️ Оскорбление сотрудников SA / поведение против стандартов клуба", Decimal("500"), False, False),
    ("greeting", "👋 Нарушение регламента приветствия гостя", Decimal("500"), True, False),
    ("collection_guest_number", "🔢 Нет номера гостя при инкассации", Decimal("250"), False, False),
    ("telegram_report", "📨 Ошибка/отсутствие Telegram-отчёта более 30 минут", Decimal("250"), False, False),
    ("empty_fridge", "🧊 Пустые места в холодильнике", Decimal("250"), False, False),
    ("overflowing_bins", "🗑 Переполненные урны более 30 минут", Decimal("250"), False, False),
    ("sleeping_guest", "😴 Спящий гость более 30 минут", Decimal("250"), False, False),
    ("game_update", "🎮 Пропущено обновление игры", Decimal("500"), False, False),
    ("device_issue", "🖥 Неработающие устройства целый день без уведомления/попытки поддержки", Decimal("500"), False, False),
    ("alcohol", "🍺 Алкоголь с гостями", Decimal("500"), False, False),
    ("guest_table_trash", "🗑 Мусор на столах гостей", Decimal("500"), False, False),
    ("pc_restore", "🧹 Место PC/PS не восстановлено более 30 минут", Decimal("500"), False, False),
    ("work_phone", "📱 Нет ответа на рабочий телефон", Decimal("500"), False, False),
    ("late_1h", "⏰ Опоздание на 1 час и более", Decimal("1000"), False, False),
    ("sleeping_admin", "😴 Сон на смене", Decimal("1000"), False, False),
    ("no_show", "🚫 Неявка на смену", Decimal("2000"), False, False),
]
RULE_MAP = {x[0]: x for x in RULES}

class PenaltyState(StatesGroup):
    waiting_comment = State()
    confirming = State()


def penalty_employee_keyboard(employees: list[Employee]) -> InlineKeyboardMarkup:
    rows = []
    for employee in employees:
        name = (employee.full_name or f"Администратор #{employee.id}").strip()
        rows.append([InlineKeyboardButton(text=f"👤 {name}"[:60], callback_data=f"penalty_employee:{employee.id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="penalty_close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def penalty_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for code, title, amount, repeat, premium in RULES:
        label = title[:36]
        if premium:
            label += " · 100% премии"
        elif repeat:
            label += " · повтор=500"
        else:
            label += f" · {amount:.0f} ₽"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"penalty_rule:{code}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="penalty_close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def penalty_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Начислить", callback_data="penalty_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="penalty_cancel")],
    ])

async def owner_only(message: Message | User):
    if isinstance(message, User):
        async with SessionLocal() as session:
            user = await session.scalar(
                select(TelegramUser).where(TelegramUser.telegram_id == message.id)
            )
    else:
        user = await get_access(message)
    if user is None or not user.active or user.role != UserRole.OWNER.value:
        if isinstance(message, Message):
            await message.answer("⛔ Только владелец.")
        return None
    return user


@router.message(F.text == "⚠️ Штрафы")
async def penalties_menu(message: Message):
    if await owner_only(message) is None:
        return
    async with SessionLocal() as session:
        employees = (await session.execute(
            select(Employee).where(Employee.active.is_(True)).order_by(Employee.full_name.asc())
        )).scalars().all()
    if not employees:
        await message.answer("❌ Активных администраторов нет. Сначала синхронизируйте LANGAME.")
        return
    await message.answer(
        "⚠️ <b>Начисление штрафа</b>\n\n"
        "Сначала выберите администратора. Технические ID сотрудника здесь не используются.",
        reply_markup=penalty_employee_keyboard(employees),
    )


@router.callback_query(F.data == "penalty_close")
async def penalty_close(callback: CallbackQuery, state: FSMContext):
    if await owner_only(callback.from_user) is None:
        await callback.answer("⛔ Только владелец", show_alert=True)
        return
    await state.clear()
    await callback.message.answer("👑 Возврат в управление администраторами.", reply_markup=admins_menu())
    await callback.answer()


@router.callback_query(F.data.startswith("penalty_employee:"))
async def penalty_employee(callback: CallbackQuery, state: FSMContext):
    if await owner_only(callback.from_user) is None:
        await callback.answer("⛔ Только владелец", show_alert=True)
        return
    try:
        employee_id = int(callback.data.split(":", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("Неверный администратор", show_alert=True)
        return
    async with SessionLocal() as session:
        employee = await session.get(Employee, employee_id)
    if employee is None or not employee.active:
        await callback.answer("Администратор не найден или неактивен", show_alert=True)
        return
    await state.update_data(penalty_employee_id=employee_id, penalty_employee_name=employee.full_name or f"Администратор #{employee_id}")
    await callback.message.edit_text(
        f"👤 <b>{employee.full_name or 'Администратор'}</b>\n\nВыберите нарушение:",
        reply_markup=penalty_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("penalty_rule:"))
async def penalty_rule(callback: CallbackQuery, state: FSMContext):
    if await owner_only(callback.from_user) is None:
        await callback.answer("⛔ Только владелец", show_alert=True)
        return
    code = callback.data.split(":", 1)[1]
    rule = RULE_MAP.get(code)
    if not rule:
        await callback.answer("Неизвестное правило", show_alert=True)
        return
    data = await state.get_data()
    employee_id = data.get("penalty_employee_id")
    if not employee_id:
        await callback.answer("Сначала выберите администратора", show_alert=True)
        return
    async with SessionLocal() as session:
        employee = await session.get(Employee, employee_id)
        if employee is None or not employee.active:
            await callback.answer("Администратор не найден или неактивен", show_alert=True)
            return
        _, title, amount, repeat, premium = rule
        previous = await session.scalar(select(func.count(SalaryViolation.id)).where(SalaryViolation.employee_id == employee_id, SalaryViolation.rule_code == code)) if (repeat or code == "insult_sa") else 0
    repeat_no = int(previous) + 1 if (repeat or code == "insult_sa") else 0
    await state.update_data(penalty_code=code, penalty_previous=int(previous), penalty_repeat_no=repeat_no)
    if code == "insult_sa":
        extra = "Первый случай — 500 ₽. Повторный случай — 100% премии за период + решение владельца об увольнении."
    elif premium:
        extra = "Последствие: снижение 100% премии за расчётный период + увольнение."
    elif repeat:
        extra = "Первый случай — предупреждение (0 ₽). Повторный — 500 ₽."
    else:
        extra = f"Размер: {amount:.0f} ₽."
    repeat_text = f"\nИстория по этому нарушению: #{repeat_no}." if repeat_no else ""
    await state.set_state(PenaltyState.waiting_comment)
    await callback.message.answer(
        f"⚠️ <b>{title}</b>\n{extra}{repeat_text}\n\n"
        "Введите комментарий к нарушению. Одной строкой, без ID сотрудника."
    )
    await callback.answer()


@router.message(PenaltyState.waiting_comment)
async def penalty_selected_input(message: Message, state: FSMContext):
    if await owner_only(message) is None:
        await state.clear()
        return
    comment = (message.text or "").strip()
    if not comment:
        await message.answer("❌ Комментарий обязателен.")
        return
    data = await state.get_data()
    code = data.get("penalty_code")
    employee_id = data.get("penalty_employee_id")
    if not code or not employee_id:
        await state.clear()
        await message.answer("❌ Сессия начисления устарела. Откройте ⚠️ Штрафы заново.")
        return
    _, title, amount, repeat, premium = RULE_MAP[code]
    previous = int(data.get("penalty_previous") or 0)
    is_repeat_dismissal = code == "insult_sa" and previous > 0
    dismissal_required = is_repeat_dismissal or premium
    final_amount = Decimal("0") if premium or is_repeat_dismissal else (Decimal("500") if repeat and previous else amount)
    consequence = (
        "100% премии за расчётный период + требуется решение владельца об увольнении"
        if is_repeat_dismissal else
        "100% премии за расчётный период + увольнение"
        if premium else
        f"{final_amount:.0f} ₽" if final_amount else "предупреждение (0 ₽)"
    )
    await state.update_data(penalty_comment=comment[:4000], penalty_amount=str(final_amount), penalty_dismissal=(premium or is_repeat_dismissal))
    await state.set_state(PenaltyState.confirming)
    employee_name = data.get("penalty_employee_name") or f"Администратор #{employee_id}"
    await message.answer(
        "🧾 <b>Проверьте начисление</b>\n\n"
        f"👤 Администратор: <b>{employee_name}</b>\n"
        f"⚠️ Нарушение: <b>{title}</b>\n"
        f"💰 Последствие: <b>{consequence}</b>\n"
        f"📝 Комментарий: {comment[:1000]}",
        reply_markup=penalty_confirmation_keyboard(),
    )


@router.callback_query(F.data == "penalty_cancel")
async def penalty_cancel(callback: CallbackQuery, state: FSMContext):
    if await owner_only(callback.from_user) is None:
        await callback.answer("⛔ Только владелец", show_alert=True)
        return
    await state.clear()
    await callback.message.answer("❌ Начисление отменено. Выберите администратора заново.")
    await callback.answer("Отменено")


@router.callback_query(F.data == "penalty_confirm")
async def penalty_confirm(callback: CallbackQuery, state: FSMContext):
    if await owner_only(callback.from_user) is None:
        await callback.answer("⛔ Только владелец", show_alert=True)
        return
    data = await state.get_data()
    employee_id = data.get("penalty_employee_id")
    code = data.get("penalty_code")
    comment = data.get("penalty_comment")
    if not employee_id or not code or not comment:
        await state.clear()
        await callback.answer("Сессия устарела", show_alert=True)
        return
    try:
        await create_manual_penalty(callback.from_user.id, employee_id, code, comment)
    except ValueError as exc:
        await state.clear()
        await callback.message.answer(f"❌ {exc}")
        await callback.answer()
        return
    await state.clear()
    _, title, amount, repeat, premium = RULE_MAP[code]
    previous = int(data.get("penalty_previous") or 0)
    is_repeat_dismissal = code == "insult_sa" and previous > 0
    dismissal_required = is_repeat_dismissal or premium
    final_amount = Decimal("0") if premium or is_repeat_dismissal else (Decimal("500") if repeat and previous else amount)
    if is_repeat_dismissal:
        text = f"🔴 Повторное нарушение «{title}» зафиксировано. 100% премии за период. Требуется решение владельца об увольнении; доступ автоматически не блокируется."
    elif premium:
        text = f"🔴 «{title}» зафиксировано. Снижение 100% премии за расчётный период + увольнение."
    elif repeat and not previous:
        text = f"⚠️ Первое нарушение «{title}» зафиксировано как предупреждение — 0 ₽."
    else:
        text = f"⚠️ Штраф {final_amount:.0f} ₽ начислен: {title}."
    await callback.message.answer(text)
    await callback.answer("Начислено")


# Technical command kept only as a compatibility fallback for existing deployments.
# The normal Owner UI never exposes employee IDs.
@router.message(lambda m: (m.text or "").startswith("/penalty"))
async def penalty_command(message: Message):
    if await owner_only(message) is None:
        return
    await message.answer("ℹ️ Ручные штрафы теперь оформляются через ⚠️ Штрафы: выберите администратора, нарушение, комментарий и подтвердите начисление.")


async def create_manual_penalty(actor_telegram_id: int, employee_id: int, code: str, comment: str):
    _, title, amount, repeat, premium = RULE_MAP[code]
    async with SessionLocal() as session:
        employee = await session.get(Employee, employee_id)
        if employee is None or not employee.active:
            raise ValueError("Администратор не найден или неактивен.")
        previous = await session.scalar(select(func.count(SalaryViolation.id)).where(SalaryViolation.employee_id == employee_id, SalaryViolation.rule_code == code)) if (repeat or code == "insult_sa") else 0
        is_repeat_dismissal = code == "insult_sa" and previous > 0
        dismissal_required = premium or is_repeat_dismissal
        final_amount = Decimal("0") if premium or is_repeat_dismissal else (Decimal("500") if repeat and previous else amount)
        source_key = f"manual:{actor_telegram_id}:{datetime.now(timezone.utc).isoformat()}:{employee_id}:{code}"
        active_shift = await session.scalar(select(Shift).where(
            Shift.employee_id == employee_id,
            Shift.ended_at.is_(None),
        ).order_by(Shift.started_at.desc()).limit(1))
        session.add(SalaryViolation(
            employee_id=employee_id,
            rule_code=code,
            title=title,
            amount=final_amount,
            source="manual",
            source_key=source_key,
            shift_id=active_shift.id if active_shift else None,
            premium_reduction_percent=100 if (premium or is_repeat_dismissal) else 0,
            dismissal_required=(premium or is_repeat_dismissal),
            comment=comment[:4000],
            created_by=actor_telegram_id,
        ))
        await write_audit(
            session,
            actor_telegram_id=actor_telegram_id,
            action="salary_penalty_added",
            entity_type="employee",
            entity_id=str(employee_id),
            payload={
                "rule": code,
                "amount": str(final_amount),
                "premium_reduction_percent": 100 if (premium or is_repeat_dismissal) else 0,
                "dismissal_required": dismissal_required,
                "comment": comment[:1000],
            },
        )
        await session.commit()

async def auto_penalty_late_report(report, employee_id: int, session) -> bool:
    if not report.first_notified_at:
        return False
    check_time = report.submitted_at or datetime.now(timezone.utc)
    if check_time <= report.first_notified_at:
        return False
    if (check_time - report.first_notified_at).total_seconds() < 30 * 60:
        return False
    source_key = f"auto:telegram_report:{report.shift_id}"
    exists = await session.scalar(select(SalaryViolation.id).where(SalaryViolation.source_key == source_key))
    if exists:
        return False
    code = "telegram_report"
    title = RULE_MAP[code][1]
    session.add(SalaryViolation(employee_id=employee_id, rule_code=code, title=title, amount=Decimal("250"), source="automatic", source_key=source_key,
                                comment="Отчёт по закрытой смене не отправлен в течение 30 минут после уведомления.", created_by=None, shift_id=report.shift_id))
    return True
