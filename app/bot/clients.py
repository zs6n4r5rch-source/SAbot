from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import delete, func, select

from app.bot.keyboards import clients_menu, owner_menu
from app.db.session import SessionLocal
from app.models import Guest, GuestGroup, GuestGroupMember, GuestTelegram, TelegramUser, UserRole
from app.services.audit import write_audit
from app.services.langame import LangameClient, langame_client

router = Router()
langame = langame_client


class ClientState(StatesGroup):
    search_query = State()
    search_phone = State()
    link_guest = State()
    link_telegram = State()


def owner_only(message: Message) -> bool:
    return bool(message.from_user)


async def is_owner(message: Message) -> bool:
    if not message.from_user:
        return False
    async with SessionLocal() as session:
        result = await session.execute(select(TelegramUser).where(TelegramUser.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        return bool(user and user.active and user.role == UserRole.OWNER.value)


def group_keyboard(groups: list[GuestGroup]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{g.name} (#{g.langame_group_id})", callback_data=f"client_group:{g.langame_group_id}")] for g in groups]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="client_groups_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def guest_keyboard(guest_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Привязать Telegram", callback_data=f"client_link:{guest_id}")],
        [InlineKeyboardButton(text="⬅️ К клиентам", callback_data="client_back")],
    ])


def format_guest(g: dict) -> str:
    gid = g.get("guest_id", "—")
    fio = g.get("fio") or "Без ФИО"
    phone = g.get("phone") or "без телефона"
    temp = "да" if g.get("temp") else "нет"
    simple = g.get("simple_reg")
    lines = [f"👤 Клиент #{gid}", f"ФИО: {fio}", f"Телефон: {phone}", f"Временный: {temp}"]
    if simple is not None:
        lines.append(f"Упрощённая регистрация: {'да' if simple else 'нет'}")
    if isinstance(g.get("balance"), dict):
        b = g["balance"]
        lines.append(f"Баланс LANGAME: {b.get('value', b.get('balance', '—'))}")
    if isinstance(g.get("bonus_balance"), dict):
        b = g["bonus_balance"]
        lines.append(f"Бонусы LANGAME: {b.get('value', b.get('balance', '—'))}")
    if g.get("black_list") is not None:
        lines.append(f"Чёрный список: {'да' if g.get('black_list') else 'нет'}")
    return "\n".join(lines)


async def sync_guests(items: list[dict], group_id: int | None = None) -> int:
    saved = 0
    async with SessionLocal() as session:
        for item in items:
            gid = item.get("guest_id")
            if gid is None:
                continue
            result = await session.execute(select(Guest).where(Guest.langame_guest_id == int(gid)))
            guest = result.scalar_one_or_none()
            if guest is None:
                guest = Guest(langame_guest_id=int(gid))
                session.add(guest)
            guest.fio = item.get("fio")
            guest.phone = item.get("phone")
            guest.is_temp = bool(item.get("temp"))
            guest.is_virtual = bool(item.get("virtual", False))
            guest.updated_at = datetime.now(timezone.utc)
            saved += 1
            if group_id is not None:
                gr = await session.execute(select(GuestGroup).where(GuestGroup.langame_group_id == group_id))
                local_group = gr.scalar_one_or_none()
                if local_group is not None:
                    exists = await session.execute(select(GuestGroupMember).where(GuestGroupMember.guest_id == guest.id, GuestGroupMember.guest_group_id == local_group.id))
                    if exists.scalar_one_or_none() is None:
                        session.add(GuestGroupMember(guest_id=guest.id, guest_group_id=local_group.id))
        await session.commit()
    return saved


@router.message(F.text == "👥 Клиенты")
async def clients(message: Message):
    if not await is_owner(message):
        await message.answer("⛔ Доступ только для владельца.")
        return
    await message.answer("👥 Клиенты\nПрофиль и группы — только чтение из LANGAME. Локально храним кэш и Telegram-привязки.", reply_markup=clients_menu())


@router.message(F.text == "🔎 Поиск")
async def search_start(message: Message, state: FSMContext):
    if not await is_owner(message):
        await message.answer("⛔ Доступ только для владельца.")
        return
    await state.set_state(ClientState.search_query)
    await message.answer("🔎 Введите ФИО, часть имени или другой текст для поиска.\nДля отмены: /cancel")


@router.message(ClientState.search_query)
async def search_query(message: Message, state: FSMContext):
    if not await is_owner(message):
        await state.clear(); return
    query = (message.text or "").strip()
    if not query:
        await message.answer("Введите поисковую строку.")
        return
    try:
        result = await langame.guests_search(query=query, size=20)
        guests = result.get("items") or result.get("data") or []
        await sync_guests(guests)
    except Exception as exc:
        await state.clear(); await message.answer(f"❌ Поиск LANGAME не выполнен: {str(exc)[:300]}"); return
    await state.clear()
    if not guests:
        await message.answer("Клиенты не найдены.", reply_markup=clients_menu()); return
    lines = ["🔎 Результаты поиска:"]
    for g in guests:
        lines.append(f"• #{g.get('guest_id','—')} — {g.get('fio') or 'Без ФИО'} — {g.get('phone') or 'без телефона'}")
    await message.answer("\n".join(lines), reply_markup=clients_menu())


@router.message(F.text == "📋 Все клиенты")
async def all_clients(message: Message):
    if not await is_owner(message):
        await message.answer("⛔ Доступ только для владельца."); return
    try:
        result = await langame.guests_search(size=50)
        guests = result.get("items") or result.get("data") or []
        await sync_guests(guests)
    except Exception as exc:
        await message.answer(f"❌ Не удалось получить клиентов: {str(exc)[:300]}"); return
    if not guests:
        await message.answer("Клиенты не найдены."); return
    lines = ["👥 Клиенты LANGAME (первая страница):"]
    for g in guests:
        lines.append(f"• #{g.get('guest_id','—')} — {g.get('fio') or 'Без ФИО'} — {g.get('phone') or 'без телефона'}")
    await message.answer("\n".join(lines))


@router.message(F.text == "🏷 Группы лояльности")
async def loyalty_groups(message: Message):
    if not await is_owner(message):
        await message.answer("⛔ Доступ только для владельца."); return
    try:
        result = await langame.guest_groups()
        groups = result.get("data") or []
    except Exception as exc:
        await message.answer(f"❌ Не удалось получить группы: {str(exc)[:300]}"); return
    async with SessionLocal() as session:
        for item in groups:
            gid = item.get("id")
            if gid is None: continue
            q = await session.execute(select(GuestGroup).where(GuestGroup.langame_group_id == int(gid)))
            g = q.scalar_one_or_none()
            if g is None:
                g = GuestGroup(langame_group_id=int(gid), name=item.get("name") or f"Группа #{gid}")
                session.add(g)
            g.name = item.get("name") or g.name
            g.percent = item.get("percent")
            g.bonus_birthday = bool(item.get("bonus_birthday")) if item.get("bonus_birthday") is not None else None
            g.updated_at = datetime.now(timezone.utc)
        await session.commit()
        local = (await session.execute(select(GuestGroup).order_by(GuestGroup.name))).scalars().all()
    if not local:
        await message.answer("Группы не найдены."); return
    await message.answer("🏷 Группы лояльности\nВыберите группу для анализа состава:", reply_markup=group_keyboard(local))


@router.callback_query(F.data.startswith("client_group:"))
async def group_members(callback: CallbackQuery):
    if not await is_owner(callback.message):
        await callback.answer("Нет доступа", show_alert=True); return
    gid = int(callback.data.split(":")[1])
    try:
        result = await langame.guests_search(groups=[gid], size=50)
        guests = result.get("items") or result.get("data") or []
        await sync_guests(guests, group_id=gid)
    except Exception as exc:
        await callback.message.answer(f"❌ Не удалось получить участников: {str(exc)[:300]}"); await callback.answer(); return
    if not guests:
        await callback.message.answer(f"Группа LANGAME #{gid}: участников не найдено."); await callback.answer(); return
    lines = [f"👥 Участники группы LANGAME #{gid} (первая страница):"]
    for g in guests:
        lines.append(f"• #{g.get('guest_id','—')} — {g.get('fio') or 'Без ФИО'} — {g.get('phone') or 'без телефона'}")
    await callback.message.answer("\n".join(lines))
    await callback.answer()


@router.callback_query(F.data == "client_groups_back")
async def groups_back(callback: CallbackQuery):
    await callback.message.answer("👥 Клиенты", reply_markup=clients_menu()); await callback.answer()


@router.message(F.text == "💬 Telegram")
async def telegram_clients(message: Message):
    if not await is_owner(message):
        await message.answer("⛔ Доступ только для владельца."); return
    async with SessionLocal() as session:
        q = await session.execute(select(GuestTelegram, Guest).join(Guest, Guest.id == GuestTelegram.guest_id).order_by(GuestTelegram.linked_at.desc()).limit(50))
        rows = q.all()
    if not rows:
        await message.answer("💬 Telegram-привязок клиентов пока нет."); return
    lines = ["💬 Привязанные Telegram:"]
    for link, guest in rows:
        consent = "✅ согласие" if link.marketing_consent else "❌ без согласия"
        lines.append(f"• #{guest.langame_guest_id} — {guest.fio or 'Без ФИО'} — TG {link.telegram_user_id} — {consent}")
    await message.answer("\n".join(lines))


@router.message(F.text == "📊 Статистика клиентов")
async def client_stats(message: Message):
    if not await is_owner(message):
        await message.answer("⛔ Доступ только для владельца."); return
    async with SessionLocal() as session:
        guests = await session.execute(select(func.count(Guest.id)))
        groups = await session.execute(select(func.count(GuestGroup.id)))
        tg = await session.execute(select(func.count(GuestTelegram.id)))
        consent = await session.execute(select(func.count(GuestTelegram.id)).where(GuestTelegram.marketing_consent.is_(True)))
    try:
        remote = await langame.guests_search(size=1)
        items = remote.get("items") or []
        remote_info = remote.get("pagination") or {}
        remote_text = f"\nLANGAME: первая страница получена, pagination={remote_info}" if remote_info else "\nLANGAME: API отвечает."
    except Exception:
        remote_text = "\nLANGAME: статистику сейчас получить не удалось."
    await message.answer(
        f"📊 Статистика клиентов\n\nЛокальный кэш: {guests.scalar() or 0}\nГрупп: {groups.scalar() or 0}\nTelegram: {tg.scalar() or 0}\nМаркетинговое согласие: {consent.scalar() or 0}"
        + remote_text
    )


@router.callback_query(F.data.startswith("client_link:"))
async def client_link_callback(callback: CallbackQuery, state: FSMContext):
    if not await is_owner(callback.message):
        await callback.answer("Нет доступа", show_alert=True); return
    guest_id = int(callback.data.split(":")[1])
    await state.update_data(guest_id=guest_id)
    await state.set_state(ClientState.link_telegram)
    await callback.message.answer(f"💬 Введите Telegram ID для клиента #{guest_id}.\nЭто изменит только локальную БД бота. LANGAME не изменяется.")
    await callback.answer()


@router.message(ClientState.link_telegram)
async def client_link_input(message: Message, state: FSMContext):
    if not await is_owner(message):
        await state.clear(); return
    try:
        tg_id = int((message.text or '').strip())
        if tg_id <= 0: raise ValueError
    except ValueError:
        await message.answer("❌ Нужен числовой Telegram ID."); return
    data = await state.get_data(); guest_langame_id = int(data["guest_id"])
    async with SessionLocal() as session:
        guest_q = await session.execute(select(Guest).where(Guest.langame_guest_id == guest_langame_id))
        guest = guest_q.scalar_one_or_none()
        if guest is None:
            await message.answer("❌ Клиент отсутствует в локальном кэше. Сначала найдите его через LANGAME."); await state.clear(); return
        old = await session.execute(select(GuestTelegram).where(GuestTelegram.telegram_user_id == tg_id))
        old_link = old.scalar_one_or_none()
        if old_link and old_link.guest_id != guest.id:
            await message.answer("❌ Этот Telegram уже привязан к другому клиенту."); await state.clear(); return
        link_q = await session.execute(select(GuestTelegram).where(GuestTelegram.guest_id == guest.id))
        link = link_q.scalar_one_or_none()
        if link is None:
            link = GuestTelegram(guest_id=guest.id, telegram_user_id=tg_id, telegram_chat_id=tg_id)
            session.add(link)
        else:
            link.telegram_user_id = tg_id; link.telegram_chat_id = tg_id
        await write_audit(session, actor_telegram_id=message.from_user.id, action="guest_telegram_linked", entity_type="guest", entity_id=str(guest.id), payload={"telegram_id": tg_id, "langame_guest_id": guest_langame_id})
        await session.commit()
    await state.clear()
    await message.answer(f"✅ Telegram {tg_id} привязан к клиенту #{guest_langame_id}.\nИзменена только БД бота.")


@router.message(Command("client"))
async def client_command(message: Message):
    if not await is_owner(message): return
    parts = (message.text or '').split()
    if len(parts) != 2:
        await message.answer("Использование: /client LANGAME_GUEST_ID"); return
    try: gid=int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный ID клиента."); return
    try:
        result = await langame.guest_by_id(gid)
        guests = result.get("items") or result.get("data") or []
    except Exception as exc:
        await message.answer(f"❌ Не удалось получить клиента: {str(exc)[:300]}"); return
    if not guests:
        await message.answer("Клиент не найден в LANGAME."); return
    await sync_guests(guests)
    await message.answer(format_guest(guests[0]), reply_markup=guest_keyboard(gid))
