from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User
from sqlalchemy import select

from app.db.session import SessionLocal
from app.bot.keyboards import admins_menu
from app.models import Employee, SalaryViolation, TelegramUser, UserRole
from app.services.audit import write_audit

router = Router()

RULES = [
    ("collection_guest_number", "Не указан номер гостя при инкассации денег", Decimal("250")),
    ("telegram_report", "Ошибка в отчёте Telegram или его отсутствие в течение 30 минут (опечатки не считаются)", Decimal("250")),
    ("empty_fridge", "Пустые места в холодильнике", Decimal("250")),
    ("overflowing_bins", "Переполненные мусорные ведра в течение 30 минут", Decimal("250")),
    ("sleeping_guest", "Спящий гость в течение 30 минут", Decimal("250")),
    ("dirty_area", "Грязь, пыль на рабочих столах после окончания сессии гостем, на рабочем месте администратора/барной стойке, посторонние предметы на столе администратора + мусор на столах гостей", Decimal("250")),
    ("late_request", "Несвоевременная заявка на замену ламп, туалетной бумаги, клининга и т. д.", Decimal("250")),
    ("greeting", "Невыполнение регламента по встрече гостя", Decimal("250")),
    ("smoking", "Курение сигарет вне специально отведённых мест", Decimal("500")),
    ("guest_drinks", "Нахождение гостя со своими напитками без оплаты пробкового сбора", Decimal("500")),
    ("uniform", "Мятая рабочая форма, отсутствие формы, неопрятный внешний вид", Decimal("500")),
    ("entrance_trash", "Наличие коробок, ящиков, упаковочных материалов и иного мусора на входе/ресепшене", Decimal("500")),
    ("cash_discipline", "Нарушение кассовой дисциплины", Decimal("500")),
    ("secret_shopper", "Провал тайного покупателя (входящий поток/звонок)", Decimal("500")),
    ("game_update", "Пропуск обновления игр", Decimal("500")),
    ("device_issue", "Нерабочие устройства в течение суток без уведомления в рабочий чат и попытки решить через поддержку", Decimal("500")),
    ("alcohol", "Алкогольные напитки у гостей", Decimal("500")),
    ("pc_restore", "Не поправленное компьютерное или PS-место в течение 30 минут", Decimal("500")),
    ("work_phone", "Нет ответа на рабочий телефон", Decimal("500")),
    ("insult_sa", "Оскорбление сотрудников, гостей, поведение, не соответствующее стандартам клуба", Decimal("500")),
    ("strangers", "Присутствие в помещении посторонних лиц в нерабочее время (не клиент)", Decimal("1000")),
    ("commercial_break", "Перерыв в ведении коммерческой деятельности в рабочие часы (за исключением обеда)", Decimal("1000")),
    ("late_1h", "Опоздание на час и более. Деньги идут админу с прошлой смены", Decimal("1000")),
    ("sleeping_admin", "Сон на смене", Decimal("1000")),
    ("discount_abuse", "Присвоение денежных средств при использовании скидок, некорректным ценником и прочее", Decimal("1000")),
    ("no_show", "Не выход на смену. Деньги идут заменяющему администратору", Decimal("2000")),
]
RULE_MAP = {x[0]: x for x in RULES}


class PenaltyState(StatesGroup):
    waiting_comment = State()
    confirming = State()


def penalty_employee_keyboard(employees: list[Employee]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"👤 {(e.full_name or f'Администратор #{e.id}')[:50]}", callback_data=f"penalty_employee:{e.id}")] for e in employees]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="penalty_close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def penalty_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{title[:50]} · {amount:.0f} ₽", callback_data=f"penalty_rule:{code}")] for code, title, amount in RULES]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="penalty_close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def penalty_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Начислить", callback_data="penalty_confirm")], [InlineKeyboardButton(text="❌ Отмена", callback_data="penalty_cancel")]])


async def owner_only(message: Message | User):
    actor_id = message.from_user.id if isinstance(message, Message) and message.from_user else message.id
    async with SessionLocal() as session:
        user = await session.scalar(select(TelegramUser).where(TelegramUser.telegram_id == actor_id))
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
        employees = (await session.execute(select(Employee).where(Employee.active.is_(True)).order_by(Employee.full_name.asc()))).scalars().all()
    if not employees:
        await message.answer("❌ Активных администраторов нет.")
        return
    await message.answer("⚠️ <b>Начисление штрафа</b>\n\nВыберите администратора:", reply_markup=penalty_employee_keyboard(employees))


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
    employee_id = int(callback.data.split(":", 1)[1])
    async with SessionLocal() as session:
        employee = await session.get(Employee, employee_id)
    if employee is None or not employee.active:
        await callback.answer("Администратор не найден", show_alert=True)
        return
    await state.update_data(penalty_employee_id=employee_id, penalty_employee_name=employee.full_name or f"Администратор #{employee_id}")
    await callback.message.edit_text(f"👤 <b>{employee.full_name or 'Администратор'}</b>\n\nВыберите нарушение:", reply_markup=penalty_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("penalty_rule:"))
async def penalty_rule(callback: CallbackQuery, state: FSMContext):
    if await owner_only(callback.from_user) is None:
        await callback.answer("⛔ Только владелец", show_alert=True)
        return
    code = callback.data.split(":", 1)[1]
    rule = RULE_MAP.get(code)
    data = await state.get_data()
    if not rule or not data.get("penalty_employee_id"):
        await callback.answer("Сессия начисления устарела", show_alert=True)
        return
    await state.update_data(penalty_code=code)
    _, title, amount = rule
    await state.set_state(PenaltyState.waiting_comment)
    await callback.message.answer(f"⚠️ <b>{title}</b>\n💰 Штраф: <b>{amount:.0f} ₽</b>\n\nВведите комментарий:")
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
    rule = RULE_MAP.get(code)
    if not rule or not employee_id:
        await state.clear()
        await message.answer("❌ Сессия начисления устарела.")
        return
    _, title, amount = rule
    await state.update_data(penalty_comment=comment[:4000])
    await state.set_state(PenaltyState.confirming)
    await message.answer(f"🧾 <b>Проверьте начисление</b>\n\n👤 {data.get('penalty_employee_name')}\n⚠️ {title}\n💰 {amount:.0f} ₽\n📝 {comment[:1000]}", reply_markup=penalty_confirmation_keyboard())


@router.callback_query(F.data == "penalty_cancel")
async def penalty_cancel(callback: CallbackQuery, state: FSMContext):
    if await owner_only(callback.from_user) is None:
        await callback.answer("⛔ Только владелец", show_alert=True)
        return
    await state.clear()
    await callback.message.answer("❌ Начисление отменено.")
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
    title = RULE_MAP[code][1]
    amount = RULE_MAP[code][2]
    await callback.message.answer(f"⚠️ Штраф {amount:.0f} ₽ начислен: {title}.")
    await callback.answer("Начислено")


@router.message(lambda m: (m.text or "").startswith("/penalty"))
async def penalty_command(message: Message):
    if await owner_only(message) is None:
        return
    await message.answer("ℹ️ Ручные штрафы оформляются через ⚠️ Штрафы.")


async def create_manual_penalty(actor_telegram_id: int, employee_id: int, code: str, comment: str):
    rule = RULE_MAP.get(code)
    if not rule:
        raise ValueError("Неизвестное нарушение.")
    _, title, amount = rule
    async with SessionLocal() as session:
        employee = await session.get(Employee, employee_id)
        if employee is None or not employee.active:
            raise ValueError("Администратор не найден.")
        source_key = f"manual:{actor_telegram_id}:{datetime.now(timezone.utc).isoformat()}:{employee_id}:{code}"
        session.add(SalaryViolation(employee_id=employee_id, rule_code=code, title=title, amount=amount, source="manual", source_key=source_key, premium_reduction_percent=0, dismissal_required=False, comment=comment[:4000], created_by=actor_telegram_id))
        await write_audit(session, actor_telegram_id=actor_telegram_id, action="salary_penalty_added", entity_type="employee", entity_id=str(employee_id), payload={"rule": code, "amount": str(amount), "comment": comment[:1000]})
        await session.commit()


async def auto_penalty_late_report(report, employee_id: int, session) -> bool:
    if not report.first_notified_at:
        return False
    check_time = report.submitted_at or datetime.now(timezone.utc)
    if check_time <= report.first_notified_at or (check_time - report.first_notified_at).total_seconds() < 30 * 60:
        return False
    source_key = f"auto:telegram_report:{report.shift_id}"
    exists = await session.scalar(select(SalaryViolation.id).where(SalaryViolation.source_key == source_key))
    if exists:
        return False
    session.add(SalaryViolation(employee_id=employee_id, rule_code="telegram_report", title=RULE_MAP["telegram_report"][1], amount=Decimal("250"), source="automatic", source_key=source_key, comment="Отчёт по закрытой смене не отправлен в течение 30 минут после уведомления.", created_by=None))
    return True
