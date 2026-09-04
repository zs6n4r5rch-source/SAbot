from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from zoneinfo import ZoneInfo

from app.db.session import SessionLocal
from app.bot.inventory import product_settings_text
from app.models import OwnerReportSettings, TelegramUser, UserRole
from app.services.audit import write_audit
from app.services.auth import get_access

router = Router()

class ReportSettingsState(StatesGroup):
    waiting_time = State()
    waiting_timezone = State()

class AddOwnerState(StatesGroup):
    waiting_telegram_id = State()

def kb(cfg: OwnerReportSettings):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("🔴 Выключить" if cfg.enabled else "🟢 Включить"), callback_data="orset:toggle")],
        [InlineKeyboardButton(text=f"⏰ Время: {cfg.report_hour:02d}:{cfg.report_minute:02d}", callback_data="orset:time")],
        [InlineKeyboardButton(text=f"🌍 Часовой пояс: {cfg.report_timezone}", callback_data="orset:tz")],
        [InlineKeyboardButton(text=f"📈 Продажи: {'ON' if cfg.include_sales else 'OFF'}", callback_data="orset:sales"), InlineKeyboardButton(text=f"📋 Смены: {'ON' if cfg.include_shifts else 'OFF'}", callback_data="orset:shifts")],
        [InlineKeyboardButton(text=f"🍔 Бар и снеки: {'ON' if cfg.include_inventory else 'OFF'}", callback_data="orset:inventory"), InlineKeyboardButton(text=f"⚠️ Расхождения: {'ON' if cfg.include_discrepancies else 'OFF'}", callback_data="orset:discrepancies")],
        [InlineKeyboardButton(text=f"💰 Зарплата: {'ON' if cfg.include_salary else 'OFF'}", callback_data="orset:salary"), InlineKeyboardButton(text=f"👤 Клиенты: {'ON' if cfg.include_clients else 'OFF'}", callback_data="orset:clients")],
        [InlineKeyboardButton(text=f"📥 Excel: {'ON' if cfg.send_excel else 'OFF'}", callback_data="orset:excel")],
    ])

async def get_owner(message: Message | CallbackQuery):
    uid = message.from_user.id if message.from_user else None
    if uid is None: return None
    async with SessionLocal() as session:
        return (await session.execute(select(TelegramUser).where(TelegramUser.telegram_id == uid, TelegramUser.active.is_(True), TelegramUser.role == UserRole.OWNER.value))).scalar_one_or_none()

async def get_cfg(uid: int) -> OwnerReportSettings:
    async with SessionLocal() as session:
        cfg = (await session.execute(select(OwnerReportSettings).where(OwnerReportSettings.owner_telegram_id == uid))).scalar_one_or_none()
        if cfg is None:
            cfg = OwnerReportSettings(owner_telegram_id=uid)
            session.add(cfg); await session.commit(); await session.refresh(cfg)
        return cfg

def render(cfg):
    return (f"⚙️ <b>Ежедневный отчёт</b>\n\n"
            f"Статус: {'🟢 включён' if cfg.enabled else '🔴 выключен'}\n"
            f"Время: <b>{cfg.report_hour:02d}:{cfg.report_minute:02d}</b> ({cfg.report_timezone})\n\n"
            "Состав: переключайте кнопками ниже.")

@router.message(F.text == "📊 Ежедневный отчёт")
async def report_settings(message: Message):
    owner = await get_owner(message)
    if not owner:
        await message.answer("⛔ Только владелец."); return
    cfg = await get_cfg(owner.telegram_id)
    await message.answer(render(cfg), reply_markup=kb(cfg))

@router.callback_query(F.data.startswith("orset:"))
async def report_settings_callback(call: CallbackQuery, state: FSMContext):
    owner = await get_owner(call)
    if not owner:
        await call.answer("⛔ Только владелец", show_alert=True); return
    cfg = await get_cfg(owner.telegram_id)
    action = call.data.split(":", 1)[1]
    field_map = {"sales":"include_sales", "shifts":"include_shifts", "inventory":"include_inventory", "discrepancies":"include_discrepancies", "salary":"include_salary", "clients":"include_clients", "excel":"send_excel"}
    if action == "toggle": cfg.enabled = not cfg.enabled
    elif action in field_map: setattr(cfg, field_map[action], not getattr(cfg, field_map[action]))
    elif action == "time":
        await state.set_state(ReportSettingsState.waiting_time); await call.message.answer("⏰ Пришлите время в формате HH:MM, например 09:00. /cancel — отмена"); await call.answer(); return
    elif action == "tz":
        await state.set_state(ReportSettingsState.waiting_timezone); await call.message.answer("🌍 Пришлите IANA timezone, например Europe/Moscow. /cancel — отмена"); await call.answer(); return
    async with SessionLocal() as session:
        db = await session.get(OwnerReportSettings, cfg.id)
        for col in field_map.values(): setattr(db, col, getattr(cfg, col))
        db.enabled = cfg.enabled
        await session.commit()
        await write_audit(session, actor_telegram_id=owner.telegram_id, action="owner_report_settings_changed", entity_type="owner_report_settings", entity_id=str(cfg.id), payload={"action": action})
    await call.message.edit_text(render(cfg), reply_markup=kb(cfg)); await call.answer("Сохранено")

@router.message(ReportSettingsState.waiting_time)
async def set_time(message: Message, state: FSMContext):
    owner = await get_owner(message)
    if not owner: await state.clear(); return
    raw=(message.text or '').strip()
    try:
        h,m=map(int,raw.split(':')); assert 0<=h<=23 and 0<=m<=59
    except Exception:
        await message.answer("❌ Формат HH:MM, например 09:00"); return
    async with SessionLocal() as session:
        cfg=(await session.execute(select(OwnerReportSettings).where(OwnerReportSettings.owner_telegram_id==owner.telegram_id))).scalar_one()
        cfg.report_hour=h; cfg.report_minute=m; await session.commit()
        await write_audit(session, actor_telegram_id=owner.telegram_id, action="owner_report_time_changed", entity_type="owner_report_settings", entity_id=str(cfg.id), payload={"hour":h,"minute":m})
    await state.clear(); cfg=await get_cfg(owner.telegram_id); await message.answer(render(cfg), reply_markup=kb(cfg))

@router.message(ReportSettingsState.waiting_timezone)
async def set_timezone(message: Message, state: FSMContext):
    owner=await get_owner(message)
    if not owner: await state.clear(); return
    raw=(message.text or '').strip()
    try: ZoneInfo(raw)
    except Exception: await message.answer("❌ Неверный IANA timezone. Например Europe/Moscow"); return
    async with SessionLocal() as session:
        cfg=(await session.execute(select(OwnerReportSettings).where(OwnerReportSettings.owner_telegram_id==owner.telegram_id))).scalar_one()
        cfg.report_timezone=raw; await session.commit()
        await write_audit(session, actor_telegram_id=owner.telegram_id, action="owner_report_timezone_changed", entity_type="owner_report_settings", entity_id=str(cfg.id), payload={"timezone":raw})
    await state.clear(); cfg=await get_cfg(owner.telegram_id); await message.answer(render(cfg), reply_markup=kb(cfg))

@router.message(F.text == "🍔 Настройки бара и снеков")
async def bar_settings(message: Message):
    user = await get_access(message)
    if user is None or user.role != UserRole.OWNER.value:
        await message.answer("⛔ Доступ только для владельца.")
        return
    await message.answer(await product_settings_text())


@router.message(F.text == "➕ Добавить владельца")
async def add_owner(message: Message, state: FSMContext):
    owner=await get_owner(message)
    if not owner: await message.answer("⛔ Только владелец."); return
    await state.set_state(AddOwnerState.waiting_telegram_id)
    await message.answer("Пришлите Telegram ID нового владельца. Он получит полный доступ владельца. /cancel — отмена")

@router.message(AddOwnerState.waiting_telegram_id)
async def add_owner_id(message: Message, state: FSMContext):
    owner=await get_owner(message)
    if not owner: return
    uid=int(message.text.strip())
    if uid==owner.telegram_id: await message.answer("Этот Telegram ID уже ваш."); return
    async with SessionLocal() as session:
        row=(await session.execute(select(TelegramUser).where(TelegramUser.telegram_id==uid))).scalar_one_or_none()
        if row is None: row=TelegramUser(telegram_id=uid, role=UserRole.OWNER.value, active=True); session.add(row)
        else: row.role=UserRole.OWNER.value; row.employee_id=None; row.active=True
        cfg=(await session.execute(select(OwnerReportSettings).where(OwnerReportSettings.owner_telegram_id==uid))).scalar_one_or_none()
        if cfg is None: session.add(OwnerReportSettings(owner_telegram_id=uid))
        await session.commit()
        await write_audit(session, actor_telegram_id=owner.telegram_id, action="owner_added", entity_type="telegram_user", entity_id=str(uid), payload={"telegram_id":uid})
    await state.clear()
    await message.answer(f"✅ Владелец {uid} добавлен. Он должен выполнить /start.")
