from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Employee, TelegramUser, UserRole
from app.models.smm import SMMTaskRate
from app.services.smm import get_smm_access, assign_smm, submit_task, smm_payroll

router = Router()


class SMMTaskState(StatesGroup):
    task_type = State()
    title = State()
    quantity = State()
    proof = State()


def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Моя аналитика", callback_data="smm:analytics")],
        [InlineKeyboardButton(text="➕ Зафиксировать работу", callback_data="smm:task")],
        [InlineKeyboardButton(text="💰 Моя оплата", callback_data="smm:salary")],
    ])


async def owner_id(message: Message | CallbackQuery):
    uid = message.from_user.id
    async with SessionLocal() as session:
        return await session.scalar(select(TelegramUser.telegram_id).where(TelegramUser.telegram_id == uid, TelegramUser.role == UserRole.OWNER.value, TelegramUser.active.is_(True)))


async def open_smm(message: Message):
    async with SessionLocal() as session:
        access = await get_smm_access(session, message.from_user.id)
    if not access:
        await message.answer("⛔ Доступ SMM не назначен.")
        return
    await message.answer("📱 <b>SMM кабинет</b>\nДоступ: соцсети, гости, маркетинг и реклама.\nОплата начисляется только по подтверждённым задачам.", reply_markup=menu())


@router.message(Command("smm"))
async def smm_command(message: Message):
    await open_smm(message)


@router.message(F.text == "📱 SMM кабинет")
async def smm_menu(message: Message):
    await open_smm(message)


@router.callback_query(F.data == "smm:analytics")
async def smm_analytics(call: CallbackQuery):
    async with SessionLocal() as session:
        access = await get_smm_access(session, call.from_user.id)
    if not access:
        await call.answer("Нет доступа", show_alert=True); return
    areas = [x.strip() for x in access.analytics_access.split(",") if x.strip()]
    await call.message.edit_text("📊 <b>Доступная аналитика SMM</b>\n\n" + "\n".join(f"• {x}" for x in areas) + "\n\nФинансы, зарплаты администраторов, штрафы, склад и служебные настройки закрыты.", reply_markup=menu())
    await call.answer()


@router.callback_query(F.data == "smm:task")
async def task_start(call: CallbackQuery, state: FSMContext):
    async with SessionLocal() as session:
        access = await get_smm_access(session, call.from_user.id)
        rates = (await session.execute(select(SMMTaskRate).where(SMMTaskRate.active.is_(True)).order_by(SMMTaskRate.title))).scalars().all()
    if not access:
        await call.answer("Нет доступа", show_alert=True); return
    buttons = [[InlineKeyboardButton(text=f"{r.title} · {r.rate} ₽/{r.unit}", callback_data=f"smm:type:{r.task_type}")] for r in rates]
    buttons.append([InlineKeyboardButton(text="Отмена", callback_data="smm:cancel")])
    await state.set_state(SMMTaskState.task_type)
    await call.message.edit_text("Выберите тип выполненной работы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()


@router.callback_query(F.data.startswith("smm:type:"))
async def task_type(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":", 2)[2]
    await state.update_data(task_type=key)
    await state.set_state(SMMTaskState.title)
    await call.message.answer("Название/описание работы. Например: «Пост о ночном тарифе». /cancel — отмена")
    await call.answer()


@router.message(SMMTaskState.title)
async def task_title(message: Message, state: FSMContext):
    async with SessionLocal() as session:
        if not await get_smm_access(session, message.from_user.id): await state.clear(); await message.answer("⛔ Нет доступа"); return
    await state.update_data(title=(message.text or "").strip()[:255])
    await state.set_state(SMMTaskState.quantity)
    await message.answer("Количество единиц работы (например, 1 или 3):")


@router.message(SMMTaskState.quantity)
async def task_quantity(message: Message, state: FSMContext):
    try: q = Decimal((message.text or "").replace(",", "."))
    except InvalidOperation: await message.answer("❌ Введите число."); return
    if q <= 0: await message.answer("❌ Количество должно быть больше нуля."); return
    await state.update_data(quantity=str(q)); await state.set_state(SMMTaskState.proof)
    await message.answer("Ссылка/подтверждение работы (если есть). Можно отправить «нет»:")


@router.message(SMMTaskState.proof)
async def task_proof(message: Message, state: FSMContext):
    async with SessionLocal() as session:
        access = await get_smm_access(session, message.from_user.id)
        if not access or not access.employee_id: await state.clear(); await message.answer("⛔ Для SMM не привязан сотрудник."); return
        data = await state.get_data()
        try:
            task = await submit_task(session, access.employee_id, data["task_type"], data["title"], Decimal(data["quantity"]), None if (message.text or "").strip().lower() == "нет" else (message.text or "").strip()[:4000])
        except ValueError as exc: await state.clear(); await message.answer(f"❌ {exc}"); return
        await session.commit()
    await state.clear()
    await message.answer(f"✅ Работа #{task.id} отправлена на подтверждение владельцу. Сумма будет начислена после подтверждения.", reply_markup=menu())


@router.callback_query(F.data == "smm:salary")
async def smm_salary(call: CallbackQuery):
    async with SessionLocal() as session:
        access = await get_smm_access(session, call.from_user.id)
        if not access or not access.employee_id: await call.answer("Нет привязанного сотрудника", show_alert=True); return
        data = await smm_payroll(session, access.employee_id, 30)
    await call.message.edit_text(f"💰 <b>Оплата SMM за 30 дней</b>\nПодтвержденных работ: {data['tasks']}\nК начислению: <b>{data['amount']} ₽</b>\n\nЧерновики и неподтверждённые работы не оплачиваются.", reply_markup=menu())
    await call.answer()


@router.message(F.text.regexp(r"^/smm_add\s+\d+$"))
async def smm_add(message: Message):
    if not await owner_id(message): await message.answer("⛔ Только владелец."); return
    tid = int(message.text.split()[1])
    async with SessionLocal() as session:
        user = await session.scalar(select(TelegramUser).where(TelegramUser.telegram_id == tid))
        if not user: await message.answer("❌ Telegram-пользователь не найден. Он должен сначала открыть бота."); return
        access = await assign_smm(session, tid)
        await session.commit()
    await message.answer(f"✅ SMM-доступ назначен Telegram ID {tid}. Аналитика: {access.analytics_access}.\nТеперь сотрудник может открыть /smm или «📱 SMM кабинет».")
