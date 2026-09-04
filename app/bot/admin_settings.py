from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import AccessProfile, Employee, TelegramUser, UserRole
from app.services.audit import write_audit

router = Router()


class AdminAccessState(StatesGroup):
    waiting_employee_id = State()
    waiting_telegram_id = State()


async def owner(message: Message | CallbackQuery) -> TelegramUser | None:
    uid = message.from_user.id if message.from_user else None
    if uid is None:
        return None
    async with SessionLocal() as session:
        return (await session.execute(
            select(TelegramUser).where(
                TelegramUser.telegram_id == uid,
                TelegramUser.active.is_(True),
                TelegramUser.role == UserRole.OWNER.value,
            )
        )).scalar_one_or_none()


def menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Список доступа", callback_data="aset:list")],
        [InlineKeyboardButton(text="➕ Привязать Telegram", callback_data="aset:bind")],
    ])


def employee_kb(employee_id: int, active: bool, linked: bool):
    rows = []
    if linked:
        rows.append([InlineKeyboardButton(
            text=("🔴 Заблокировать доступ" if active else "🟢 Разрешить доступ"),
            callback_data=f"aset:toggle:{employee_id}",
        )])
        rows.append([InlineKeyboardButton(text="🔗 Сменить Telegram", callback_data=f"aset:rebind:{employee_id}")])
    else:
        rows.append([InlineKeyboardButton(text="🔗 Привязать Telegram", callback_data=f"aset:rebind:{employee_id}")])
    rows.append([InlineKeyboardButton(text="📜 Журнал действий", callback_data=f"aset:audit:{employee_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "👤 Управление администраторами")
async def admin_settings(message: Message):
    if not await owner(message):
        await message.answer("⛔ Только владелец.")
        return
    await message.answer(
        "⚙️ <b>Управление администраторами</b>\n\n"
        "Здесь меняется только доступ к Telegram-боту.\n"
        "Статус администратора в LANGAME не изменяется.",
        reply_markup=menu_kb(),
    )


@router.callback_query(F.data == "aset:list")
async def admin_access_list(call: CallbackQuery):
    if not await owner(call):
        await call.answer("⛔ Только владелец", show_alert=True)
        return
    async with SessionLocal() as session:
        employees = (await session.execute(
            select(Employee).order_by(Employee.active.desc(), Employee.full_name.asc())
        )).scalars().all()
        users = (await session.execute(
            select(TelegramUser).where(TelegramUser.role == UserRole.ADMIN.value)
        )).scalars().all()
    by_employee = {u.employee_id: u for u in users if u.employee_id is not None}
    if not employees:
        await call.message.edit_text("👤 Администраторов нет. Сначала синхронизируйте LANGAME.", reply_markup=menu_kb())
        await call.answer()
        return
    lines = ["👤 <b>Доступ администраторов</b>", ""]
    buttons = []
    for e in employees:
        tg = by_employee.get(e.id)
        if tg:
            access = "🟢 доступ" if tg.active else "🔴 заблокирован"
            tg_text = str(tg.telegram_id)
        else:
            access = "⚪ не привязан"
            tg_text = "—"
        lines.append(f"#{e.id} — {e.full_name or 'Без ФИО'}\nLANGAME: {e.langame_user_id} • TG: {tg_text} • {access}")
        buttons.append([InlineKeyboardButton(text=f"⚙️ #{e.id} {e.full_name or 'Без ФИО'}"[:60], callback_data=f"aset:employee:{e.id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="aset:back")])
    await call.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()


@router.callback_query(F.data.startswith("aset:employee:"))
async def employee_detail(call: CallbackQuery):
    if not await owner(call):
        await call.answer("⛔ Только владелец", show_alert=True)
        return
    eid = int(call.data.rsplit(":", 1)[1])
    async with SessionLocal() as session:
        emp = await session.get(Employee, eid)
        tg = (await session.execute(select(TelegramUser).where(
            TelegramUser.employee_id == eid,
            TelegramUser.role == UserRole.ADMIN.value,
        ))).scalar_one_or_none()
        profile = (await session.execute(select(AccessProfile).where(AccessProfile.employee_id == eid))).scalar_one_or_none()
    if not emp:
        await call.answer("Сотрудник не найден", show_alert=True)
        return
    text = (
        f"👤 <b>{emp.full_name or 'Без ФИО'}</b>\n"
        f"ID: #{emp.id}\nLANGAME: {emp.langame_user_id}\n"
        f"Телефон: {emp.phone or '—'}\n"
        f"Статус LANGAME: {'активен' if emp.active else 'неактивен'}\n"
        f"Telegram: {tg.telegram_id if tg else 'не привязан'}\n"
        f"Доступ бота: {'разрешён' if tg and tg.active else 'заблокирован/не привязан'}\n"
        f"\n💰 Оплата за смену: {profile.salary_per_shift if profile and profile.salary_per_shift is not None else '—'} ₽\n"
        f"🏆 Бонусы: {'стандартные условия' if profile and profile.role == UserRole.ADMIN.value else '—'}\n"
        f"📅 Дата начала: {profile.employment_start_date or 'не указана' if profile else 'не указана'}\n"
        f"📝 Примечание: {profile.notes or '—' if profile else '—'}"
    )
    await call.message.edit_text(text, reply_markup=employee_kb(emp.id, bool(tg and tg.active), bool(tg)))
    await call.answer()


@router.callback_query(F.data.startswith("aset:toggle:"))
async def toggle_access(call: CallbackQuery):
    actor = await owner(call)
    if not actor:
        await call.answer("⛔ Только владелец", show_alert=True)
        return
    eid = int(call.data.rsplit(":", 1)[1])
    async with SessionLocal() as session:
        tg = (await session.execute(select(TelegramUser).where(
            TelegramUser.employee_id == eid,
            TelegramUser.role == UserRole.ADMIN.value,
        ))).scalar_one_or_none()
        if not tg:
            await call.answer("Telegram не привязан", show_alert=True)
            return
        tg.active = not tg.active
        new_state = tg.active
        await session.commit()
        await write_audit(
            session,
            actor_telegram_id=actor.telegram_id,
            action="admin_bot_access_changed",
            entity_type="employee",
            entity_id=str(eid),
            payload={"employee_id": eid, "telegram_id": tg.telegram_id, "active": new_state},
        )
    await call.answer("Доступ включён" if new_state else "Доступ заблокирован")
    await employee_detail(call)


@router.callback_query(F.data.startswith("aset:rebind:"))
async def rebind_start(call: CallbackQuery, state: FSMContext):
    if not await owner(call):
        await call.answer("⛔ Только владелец", show_alert=True)
        return
    eid = int(call.data.rsplit(":", 1)[1])
    async with SessionLocal() as session:
        emp = await session.get(Employee, eid)
    if not emp:
        await call.answer("Сотрудник не найден", show_alert=True)
        return
    await state.update_data(employee_id=eid)
    await state.set_state(AdminAccessState.waiting_telegram_id)
    await call.message.answer(
        f"🔗 Смена Telegram для #{eid} — {emp.full_name or 'Без ФИО'}\n\n"
        "Пришлите новый числовой Telegram ID.\n"
        "Старый доступ будет отвязан. /cancel — отмена"
    )
    await call.answer()


@router.callback_query(F.data == "aset:bind")
async def bind_start(call: CallbackQuery, state: FSMContext):
    if not await owner(call):
        await call.answer("⛔ Только владелец", show_alert=True)
        return
    await state.set_state(AdminAccessState.waiting_employee_id)
    await call.message.answer("Введите ID администратора из списка LANGAME. /cancel — отмена")
    await call.answer()


@router.message(AdminAccessState.waiting_employee_id)
async def bind_employee(message: Message, state: FSMContext):
    if not await owner(message):
        await state.clear(); await message.answer("⛔ Только владелец."); return
    try:
        eid = int((message.text or '').strip())
    except ValueError:
        await message.answer("❌ Нужен числовой ID администратора."); return
    async with SessionLocal() as session:
        emp = await session.get(Employee, eid)
    if not emp:
        await message.answer("❌ Администратор не найден."); return
    await state.update_data(employee_id=eid)
    await state.set_state(AdminAccessState.waiting_telegram_id)
    await message.answer(f"Администратор: #{eid} — {emp.full_name or 'Без ФИО'}\nПришлите Telegram ID.")


@router.message(AdminAccessState.waiting_telegram_id)
async def bind_telegram(message: Message, state: FSMContext):
    actor = await owner(message)
    if not actor:
        await state.clear(); await message.answer("⛔ Только владелец."); return
    try:
        tid = int((message.text or '').strip())
        if tid <= 0: raise ValueError
    except ValueError:
        await message.answer("❌ Нужен положительный числовой Telegram ID."); return
    data = await state.get_data()
    eid = int(data["employee_id"])
    async with SessionLocal() as session:
        emp = await session.get(Employee, eid)
        if not emp:
            await state.clear(); await message.answer("❌ Администратор не найден."); return
        current = (await session.execute(select(TelegramUser).where(TelegramUser.employee_id == eid))).scalars().all()
        target = (await session.execute(select(TelegramUser).where(TelegramUser.telegram_id == tid))).scalar_one_or_none()
        for row in current:
            if row.telegram_id != tid:
                row.employee_id = None
                row.active = False
        if target is not None and target.employee_id not in (None, eid):
            # A Telegram identity can belong to only one administrator.
            target.employee_id = None
            target.active = False
        if target is None:
            target = TelegramUser(telegram_id=tid, role=UserRole.ADMIN.value, employee_id=eid, active=True)
            session.add(target)
        else:
            target.role = UserRole.ADMIN.value
            target.employee_id = eid
            target.active = True
        await session.commit()
        await write_audit(
            session,
            actor_telegram_id=actor.telegram_id,
            action="admin_telegram_rebound",
            entity_type="employee",
            entity_id=str(eid),
            payload={"employee_id": eid, "telegram_id": tid},
        )
    await state.clear()
    await message.answer(f"✅ Telegram {tid} привязан к администратору #{eid}. Старый доступ отключён.")


@router.callback_query(F.data.startswith("aset:audit:"))
async def admin_audit(call: CallbackQuery):
    if not await owner(call):
        await call.answer("⛔ Только владелец", show_alert=True); return
    eid = int(call.data.rsplit(":", 1)[1])
    from app.models import AuditLog
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(AuditLog).where(
                AuditLog.entity_type == "employee",
                AuditLog.entity_id == str(eid),
            ).order_by(AuditLog.created_at.desc()).limit(15)
        )).scalars().all()
    if not rows:
        text = f"📜 Журнал #{eid}\n\nЗаписей нет."
    else:
        text = "📜 <b>Журнал действий</b>\n\n" + "\n".join(
            f"{r.created_at:%d.%m %H:%M} • {r.action} • Владелец {r.actor_telegram_id}"
            for r in rows
        )
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К администратору", callback_data=f"aset:employee:{eid}")],
        [InlineKeyboardButton(text="👤 К списку", callback_data="aset:list")],
    ]))
    await call.answer()


@router.callback_query(F.data == "aset:back")
async def admin_settings_back(call: CallbackQuery):
    if not await owner(call):
        await call.answer("⛔ Только владелец", show_alert=True); return
    await call.message.edit_text("⚙️ <b>Управление администраторами</b>", reply_markup=menu_kb())
    await call.answer()
