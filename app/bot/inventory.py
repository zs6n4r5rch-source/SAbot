from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select, func, desc

from app.bot.keyboards import admin_menu, owner_menu, inventory_menu
from app.db.session import SessionLocal
from app.models import (
    Club, Employee, InventoryBalance, InventoryOperation, Product,
    StockSnapshot, TelegramUser, UserRole, Writeoff, WriteoffItem, WriteoffReason, WriteoffStatus,
    Inventory, InventoryItem, InventoryStatus, Discrepancy, DiscrepancyStatus,
)
from app.services.auth import get_access
from app.services.langame import LangameClient, langame_client, LangameAPIError
from app.services.audit import write_audit

router = Router()
langame = langame_client


async def access(message: Message):
    if not message.from_user:
        return None
    return await get_access(message)


class InventoryState(StatesGroup):
    waiting_club = State()
    counting = State()


class WriteoffState(StatesGroup):
    waiting_product = State()
    waiting_quantity = State()
    waiting_reason = State()
    waiting_comment = State()


def _num(v, default=0):
    try:
        return Decimal(str(v if v is not None else default))
    except Exception:
        return Decimal(str(default))


def _apply_langame_delta(previous_langame: Decimal | None, new_langame: Decimal, control_quantity: Decimal | None) -> Decimal:
    """Keep local control balance aligned with external LANGAME changes.

    Local write-offs/reconciliation are preserved; only the delta since the
    previous LANGAME snapshot is applied to the local control balance.
    """
    if previous_langame is None or control_quantity is None:
        return new_langame
    return control_quantity + (new_langame - previous_langame)


async def sync_inventory_data() -> tuple[int, int, int, int]:
    """Sync clubs/products and take current LANGAME stock snapshots.

    /goods/list is the authoritative warehouse balance endpoint and requires club_id.
    """
    clubs_result = await langame.clubs()
    products_result = await langame.products()
    clubs = clubs_result.get("data") or []
    products = products_result.get("data") or []

    async with SessionLocal() as session:
        club_map = {}
        for item in clubs:
            cid = item.get("id")
            if cid is None:
                continue
            club = (await session.execute(select(Club).where(Club.langame_club_id == int(cid)))).scalar_one_or_none()
            if club is None:
                club = Club(langame_club_id=int(cid), name=item.get("name") or f"Клуб #{cid}")
                session.add(club)
            club.name = item.get("name") or club.name
            club.active = bool(item.get("active", 1))
            club_map[int(cid)] = club

        product_map = {}
        for item in products:
            pid = item.get("id")
            if pid is None:
                continue
            product = (await session.execute(select(Product).where(Product.langame_product_id == int(pid)))).scalar_one_or_none()
            if product is None:
                product = Product(langame_product_id=int(pid), name=item.get("name") or f"Товар #{pid}")
                session.add(product)
            product.name = item.get("name") or product.name
            product.active = bool(item.get("active", 1))
            product_map[int(pid)] = product
        await session.flush()

        stock_rows = 0
        for langame_club_id, club in club_map.items():
            result = await langame.stock(langame_club_id)
            rows = result.get("data") or []
            for row in rows:
                pid = row.get("id")
                if pid is None or int(pid) not in product_map:
                    continue
                product = product_map[int(pid)]
                qty = _num(row.get("count"))
                previous_snapshot = (await session.execute(
                    select(StockSnapshot).where(
                        StockSnapshot.club_id == club.id,
                        StockSnapshot.product_id == product.id,
                    ).order_by(StockSnapshot.captured_at.desc()).limit(1)
                )).scalar_one_or_none()
                snapshot = StockSnapshot(club_id=club.id, product_id=product.id, quantity=qty)
                session.add(snapshot)
                balance = (await session.execute(select(InventoryBalance).where(
                    InventoryBalance.club_id == club.id,
                    InventoryBalance.product_id == product.id,
                ))).scalar_one_or_none()
                if balance is None:
                    balance = InventoryBalance(club_id=club.id, product_id=product.id, quantity=qty)
                    session.add(balance)
                else:
                    balance.quantity = max(Decimal("0"), _apply_langame_delta(
                        previous_snapshot.quantity if previous_snapshot else None, qty, balance.quantity
                    ))
                stock_rows += 1
        await session.commit()
    return len(clubs), len(products), stock_rows, 0


@router.message(F.text == "🍔 Бар и снеки")
async def inventory_menu_handler(message: Message):
    user = await access(message)
    if user is None:
        await message.answer("⛔ Доступ не настроен. Обратитесь к владельцу клуба.")
        return
    await message.answer("🍔 Бар и снеки\nВыберите раздел:", reply_markup=inventory_menu())


@router.message(F.text == "🔄 Обновить остатки")
async def sync_inventory(message: Message):
    user = await access(message)
    if user is None:
        await message.answer("⛔ Доступ не настроен. Обратитесь к владельцу клуба.")
        return
    try:
        clubs, products, stock_rows, _ = await sync_inventory_data()
        await message.answer(f"✅ Бар и снеки синхронизированы из LANGAME.\nКлубов: {clubs}\nТоваров: {products}\nПозиция остатков: {stock_rows}")
    except LangameAPIError as exc:
        await message.answer(f"❌ LANGAME: {str(exc)[:500]}")
    except Exception as exc:
        await message.answer(f"❌ Ошибка синхронизации: {str(exc)[:500]}")


async def format_stock(club_id: int | None = None, limit: int = 40):
    async with SessionLocal() as session:
        stmt = select(InventoryBalance, Product, Club).join(Product, Product.id == InventoryBalance.product_id).join(Club, Club.id == InventoryBalance.club_id).order_by(Product.name)
        if club_id:
            stmt = stmt.where(InventoryBalance.club_id == club_id)
        rows = (await session.execute(stmt.limit(limit))).all()
    if not rows:
        return "Остатки пока пусты. Нажмите «🔄 Обновить остатки»."
    lines = ["📦 Остатки:"]
    current_club = None
    for balance, product, club in rows:
        if club.name != current_club:
            current_club = club.name
            lines.append(f"\n🏢 {club.name}")
        low = " ⚠️ МАЛО" if balance.min_stock > 0 and balance.quantity <= balance.min_stock else ""
        lines.append(f"• {product.name}: {balance.quantity:g}{low}")
    return "\n".join(lines)


@router.message(F.text == "📦 Остатки")
async def stock(message: Message):
    user = await access(message)
    if user is None:
        await message.answer("⛔ Доступ не настроен. Обратитесь к владельцу клуба.")
        return
    await message.answer(await format_stock())


@router.message(F.text == "📥 Приходы")
async def arrivals(message: Message):
    user = await access(message)
    if user is None:
        await message.answer("⛔ Доступ не настроен. Обратитесь к владельцу клуба.")
        return
    date_from = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        result = await langame.product_arrivals(date_from, date_to, page=1, page_limit=50)
        rows = result.get("data") or []
        if not rows:
            await message.answer("📥 За последние 30 дней приходы не найдены.")
            return
        lines = ["📥 Приходы LANGAME за 30 дней:"]
        for row in rows[:30]:
            name = row.get("name") or row.get("product_name") or f"Товар #{row.get('product_id', '—')}"
            qty = row.get("count", row.get("quantity", "—"))
            date = row.get("date", row.get("created_at", ""))
            lines.append(f"• {name}: +{qty} {date}")
        await message.answer("\n".join(lines))
    except Exception as exc:
        await message.answer(f"❌ Не удалось получить приходы: {str(exc)[:400]}")


@router.message(F.text == "📈 Продажи бара и снеков")
async def sales(message: Message):
    user = await access(message)
    if user is None:
        await message.answer("⛔ Доступ не настроен. Обратитесь к владельцу клуба.")
        return
    date_from = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        result = await langame.product_sales(date_from, date_to, page=1, page_limit=100)
        rows = result.get("data") or []
        if not rows:
            await message.answer("📈 За последние 30 дней продажи не найдены.")
            return
        lines = ["📈 Продажи LANGAME за 30 дней:"]
        for row in rows[:30]:
            name = row.get("name") or row.get("product_name") or f"Товар #{row.get('product_id', '—')}"
            qty = row.get("count", row.get("quantity", "—"))
            total = row.get("sum", row.get("amount", "—"))
            lines.append(f"• {name}: {qty} шт. — {total}")
        await message.answer("\n".join(lines))
    except Exception as exc:
        await message.answer(f"❌ Не удалось получить продажи: {str(exc)[:400]}")


@router.message(F.text == "📜 История бара и снеков")
async def inventory_history(message: Message):
    user = await access(message)
    if user is None:
        await message.answer("⛔ Доступ не настроен. Обратитесь к владельцу клуба.")
        return
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(InventoryOperation, Product, Club)
            .join(Product, Product.id == InventoryOperation.product_id)
            .join(Club, Club.id == InventoryOperation.club_id)
            .order_by(desc(InventoryOperation.created_at)).limit(30)
        )).all()
    if not rows:
        await message.answer("📜 История операций бара и снеков пока пуста.")
        return
    labels = {"arrival": "приход", "sale": "продажа", "writeoff": "списание", "inventory_adjustment": "инвентаризация", "manual_adjustment": "корректировка"}
    lines = ["📜 История бара и снеков:"]
    for op, product, club in rows:
        lines.append(f"• {op.created_at:%d.%m %H:%M} | {labels.get(op.operation_type, op.operation_type)} | {product.name} | {op.quantity:g} | {club.name}")
    await message.answer("\n".join(lines))




async def _active_employee(user):
    if not user.employee_id:
        return None
    async with SessionLocal() as session:
        return (await session.execute(select(Employee).where(Employee.id == user.employee_id))).scalar_one_or_none()


async def _start_inventory(message: Message, state: FSMContext):
    user = await access(message)
    if user is None:
        await message.answer("⛔ Доступ не настроен. Обратитесь к владельцу клуба.")
        return
    async with SessionLocal() as session:
        clubs = (await session.execute(select(Club).where(Club.active.is_(True)).order_by(Club.name))).scalars().all()
    if not clubs:
        await message.answer("❌ Нет активных клубов. Сначала выполните «🔄 Обновить остатки».")
        return
    await state.set_state(InventoryState.waiting_club)
    lines = ["🧮 Новая инвентаризация\n", "Выберите клуб, отправив его ID:"]
    lines += [f"{c.id} — {c.name} (LANGAME {c.langame_club_id})" for c in clubs]
    lines.append("\n/cancel — отмена")
    await message.answer("\n".join(lines))


@router.message(F.text == "🧮 Инвентаризации")
async def inventory_start(message: Message, state: FSMContext):
    await _start_inventory(message, state)


@router.message(InventoryState.waiting_club)
async def inventory_choose_club(message: Message, state: FSMContext):
    user = await access(message)
    if user is None:
        await state.clear()
        await message.answer("⛔ Доступ не настроен.")
        return
    try:
        club_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Введите числовой ID клуба из списка.")
        return
    async with SessionLocal() as session:
        club = (await session.execute(select(Club).where(Club.id == club_id, Club.active.is_(True)))).scalar_one_or_none()
        if not club:
            await message.answer("❌ Клуб не найден.")
            return
        active = (await session.execute(
            select(Inventory).where(Inventory.club_id == club.id, Inventory.status == InventoryStatus.IN_PROGRESS.value)
        )).scalar_one_or_none()
        if active:
            await message.answer(f"⚠️ В клубе уже есть незавершённая инвентаризация #{active.id}.")
            await state.clear()
            return
        inventory = Inventory(
            club_id=club.id, created_by=message.from_user.id,
            status=InventoryStatus.IN_PROGRESS.value, started_at=datetime.now(timezone.utc)
        )
        session.add(inventory)
        await session.flush()
        balances = (await session.execute(
            select(InventoryBalance, Product)
            .join(Product, Product.id == InventoryBalance.product_id)
            .where(InventoryBalance.club_id == club.id, Product.active.is_(True))
            .order_by(Product.name)
        )).all()
        if not balances:
            await session.delete(inventory)
            await session.commit()
            await state.clear()
            await message.answer("❌ В этом клубе нет товаров с остатками. Сначала обновите остатки.")
            return
        for balance, product in balances:
            session.add(InventoryItem(
                inventory_id=inventory.id, product_id=product.id,
                system_quantity=balance.quantity
            ))
        await session.commit()
        item_ids = [item[0].id for item in []]  # keep FSM payload minimal
        count = len(balances)
    await state.update_data(inventory_id=inventory.id, index=0)
    await state.set_state(InventoryState.counting)
    await _ask_inventory_item(message, state)


async def _ask_inventory_item(message: Message, state: FSMContext):
    data = await state.get_data()
    inventory_id = int(data["inventory_id"])
    index = int(data.get("index", 0))
    async with SessionLocal() as session:
        items = (await session.execute(
            select(InventoryItem, Product)
            .join(Product, Product.id == InventoryItem.product_id)
            .where(InventoryItem.inventory_id == inventory_id)
            .order_by(InventoryItem.id)
        )).all()
    if index >= len(items):
        await _finish_inventory(message, state)
        return
    item, product = items[index]
    await message.answer(
        f"🧮 Инвентаризация #{inventory_id}\n"
        f"Позиция {index + 1}/{len(items)}\n\n"
        f"📦 {product.name}\n"
        f"Системный остаток: {item.system_quantity:g}\n\n"
        "Введите фактическое количество:"
    )


@router.message(InventoryState.counting)
async def inventory_count(message: Message, state: FSMContext):
    user = await access(message)
    if user is None:
        await state.clear()
        await message.answer("⛔ Доступ не настроен.")
        return
    try:
        qty = Decimal((message.text or "").replace(",", ".").strip())
        if qty < 0:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите число 0 или больше.")
        return
    data = await state.get_data()
    inventory_id = int(data["inventory_id"])
    index = int(data.get("index", 0))
    async with SessionLocal() as session:
        items = (await session.execute(
            select(InventoryItem).where(InventoryItem.inventory_id == inventory_id).order_by(InventoryItem.id)
        )).scalars().all()
        if index >= len(items):
            await _finish_inventory(message, state)
            return
        item = items[index]
        item.actual_quantity = qty
        item.difference = qty - item.system_quantity
        await session.commit()
    await state.update_data(index=index + 1)
    await _ask_inventory_item(message, state)


async def _finish_inventory(message: Message, state: FSMContext):
    data = await state.get_data()
    inventory_id = int(data["inventory_id"])
    async with SessionLocal() as session:
        inventory = (await session.execute(select(Inventory).where(Inventory.id == inventory_id))).scalar_one_or_none()
        if not inventory:
            await state.clear()
            await message.answer("❌ Инвентаризация не найдена.")
            return
        items = (await session.execute(select(InventoryItem).where(InventoryItem.inventory_id == inventory_id))).scalars().all()
        missing = [x for x in items if x.actual_quantity is None]
        if missing:
            await message.answer("❌ Не все позиции пересчитаны. Продолжите ввод количества.")
            return
        # A discrepancy is a separate business fact; we do not silently alter LANGAME/system stock here.
        for old in (await session.execute(select(Discrepancy).where(Discrepancy.inventory_id == inventory_id))).scalars().all():
            await session.delete(old)
        created = 0
        for item in items:
            diff = item.difference or Decimal("0")
            if diff == 0:
                continue
            session.add(Discrepancy(
                club_id=inventory.club_id, inventory_id=inventory.id, product_id=item.product_id,
                quantity_difference=diff, status=DiscrepancyStatus.OPEN.value,
                reason="Расхождение по результатам инвентаризации"
            ))
            created += 1
        inventory.status = InventoryStatus.COMPLETED.value
        inventory.completed_at = datetime.now(timezone.utc)
        await session.commit()
    await state.clear()
    await message.answer(
        f"✅ Инвентаризация #{inventory_id} завершена.\n"
        f"Расхождений: {created}.\n\n"
        "Системные остатки автоматически не изменялись. Расхождения вынесены отдельно для владельца."
    )


@router.message(F.text == "⚠️ Расхождения")
async def discrepancies(message: Message):
    user = await access(message)
    if user is None:
        await message.answer("⛔ Доступ не настроен. Обратитесь к владельцу клуба.")
        return
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(Discrepancy, Product, Club)
            .join(Product, Product.id == Discrepancy.product_id)
            .join(Club, Club.id == Discrepancy.club_id)
            .where(Discrepancy.status.in_([DiscrepancyStatus.OPEN.value, DiscrepancyStatus.REVIEWED.value]))
            .order_by(desc(Discrepancy.created_at)).limit(50)
        )).all()
    if not rows:
        await message.answer("⚠️ Открытых расхождений нет.")
        return
    lines = ["⚠️ Расхождения для владельца:"]
    for d, product, club in rows:
        sign = "+" if d.quantity_difference > 0 else ""
        lines.append(f"• #{d.id} | {d.status} | {club.name} | {product.name}: {sign}{d.quantity_difference:g}")
    if user.role == UserRole.OWNER.value:
        lines.append("\nПросмотр: /review_discrepancy ID\nПодтвердить корректировку: /resolve_discrepancy ID комментарий")
    await message.answer("\n".join(lines))


@router.message(Command("review_discrepancy"))
async def review_discrepancy(message: Message):
    user = await access(message)
    if user is None or user.role != UserRole.OWNER.value:
        await message.answer("⛔ Действие доступно только владельца.")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip().isdigit():
        await message.answer("Формат: /review_discrepancy ID")
        return
    did = int(parts[1].strip())
    async with SessionLocal() as session:
        row = (await session.execute(
            select(Discrepancy, Product, Club, Inventory)
            .join(Product, Product.id == Discrepancy.product_id)
            .join(Club, Club.id == Discrepancy.club_id)
            .outerjoin(Inventory, Inventory.id == Discrepancy.inventory_id)
            .where(Discrepancy.id == did)
        )).first()
        if not row:
            await message.answer("❌ Расхождение не найдено.")
            return
        d, product, club, inventory = row
        if d.status == DiscrepancyStatus.RESOLVED.value:
            await message.answer("ℹ️ Это расхождение уже закрыто.")
            return
        if d.status == DiscrepancyStatus.OPEN.value:
            d.status = DiscrepancyStatus.REVIEWED.value
            await session.commit()
            await write_audit(session, actor_telegram_id=message.from_user.id, action="review_discrepancy", entity_type="discrepancy", entity_id=str(d.id), payload={"quantity_difference": str(d.quantity_difference)})
        await message.answer(
            f"🔎 Расхождение #{d.id}\n\n"
            f"Клуб: {club.name}\n"
            f"Товар: {product.name}\n"
            f"Разница: {'+' if d.quantity_difference > 0 else ''}{d.quantity_difference:g}\n"
            f"Инвентаризация: #{inventory.id if inventory else '—'}\n"
            f"Причина: {d.reason or '—'}\n\n"
            "Для подтверждения корректировки: /resolve_discrepancy ID комментарий\n"
            "Корректировка меняет только внутренний остаток бота и НЕ отправляется в LANGAME."
        )


@router.message(Command("resolve_discrepancy"))
async def resolve_discrepancy(message: Message):
    user = await access(message)
    if user is None or user.role != UserRole.OWNER.value:
        await message.answer("⛔ Действие доступно только владельца.")
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.answer("Формат: /resolve_discrepancy ID комментарий")
        return
    did = int(parts[1].strip())
    comment = parts[2].strip() if len(parts) == 3 else "Подтверждено владельцем"
    async with SessionLocal() as session:
        row = (await session.execute(
            select(Discrepancy, Product, Club)
            .join(Product, Product.id == Discrepancy.product_id)
            .join(Club, Club.id == Discrepancy.club_id)
            .where(Discrepancy.id == did)
            .with_for_update()
        )).first()
        if not row:
            await message.answer("❌ Расхождение не найдено.")
            return
        d, product, club = row
        if d.status == DiscrepancyStatus.RESOLVED.value:
            await message.answer("ℹ️ Расхождение уже закрыто. Повторная корректировка не выполнена.")
            return
        if d.status != DiscrepancyStatus.REVIEWED.value:
            await message.answer("❌ Сначала выполните проверку: /review_discrepancy ID")
            return
        balance = (await session.execute(
            select(InventoryBalance)
            .where(InventoryBalance.club_id == d.club_id, InventoryBalance.product_id == d.product_id)
            .with_for_update()
        )).scalar_one_or_none()
        if balance is None:
            if d.quantity_difference < 0:
                await message.answer("❌ Внутренний остаток не найден, отрицательную корректировку применить нельзя.")
                return
            balance = InventoryBalance(club_id=d.club_id, product_id=d.product_id, quantity=Decimal("0"))
            session.add(balance)
            await session.flush()
        new_quantity = balance.quantity + d.quantity_difference
        if new_quantity < 0:
            await message.answer(f"❌ Корректировка дала бы отрицательный остаток: {new_quantity:g}.")
            return
        old_quantity = balance.quantity
        balance.quantity = new_quantity
        d.status = DiscrepancyStatus.RESOLVED.value
        d.resolved_by = message.from_user.id
        d.resolved_at = datetime.now(timezone.utc)
        d.resolution_comment = comment
        session.add(InventoryOperation(
            club_id=d.club_id, product_id=d.product_id, employee_id=d.employee_id, shift_id=d.shift_id,
            operation_type="inventory_adjustment", quantity=d.quantity_difference,
            source="discrepancy", source_id=str(d.id),
            comment=comment,
        ))
        await session.commit()
        await write_audit(
            session, actor_telegram_id=message.from_user.id, action="resolve_discrepancy",
            entity_type="discrepancy", entity_id=str(d.id),
            payload={
                "product_id": d.product_id, "club_id": d.club_id,
                "delta": str(d.quantity_difference), "old_quantity": str(old_quantity),
                "new_quantity": str(new_quantity), "comment": comment,
            }
        )
    await message.answer(
        f"✅ Расхождение #{did} закрыто.\n"
        f"{product.name}: {old_quantity:g} → {new_quantity:g}\n"
        f"Корректировка: {'+' if d.quantity_difference > 0 else ''}{d.quantity_difference:g}\n\n"
        "⚠️ LANGAME не изменялся. Операция записана только во внутреннюю историю бара и снеков."
    )


@router.message(Command("cancel"), InventoryState.waiting_club)
@router.message(Command("cancel"), InventoryState.counting)
async def cancel_inventory(message: Message, state: FSMContext):
    data = await state.get_data()
    inventory_id = data.get("inventory_id")
    if inventory_id:
        async with SessionLocal() as session:
            inventory = (await session.execute(select(Inventory).where(Inventory.id == int(inventory_id)))).scalar_one_or_none()
            if inventory and inventory.status == InventoryStatus.IN_PROGRESS.value:
                inventory.status = InventoryStatus.CANCELLED.value
                await session.commit()
    await state.clear()
    await message.answer("🚫 Инвентаризация отменена.")


@router.message(F.text == "📝 Списание")
async def writeoff_start(message: Message, state: FSMContext):
    user = await access(message)
    if user is None:
        await message.answer("⛔ Доступ не настроен. Обратитесь к владельцу клуба.")
        return
    async with SessionLocal() as session:
        rows = (await session.execute(select(Product).where(Product.active.is_(True)).order_by(Product.name).limit(50))).scalars().all()
    if not rows:
        await message.answer("Нет активных товаров. Сначала обновите бар и снеки.")
        return
    await state.set_state(WriteoffState.waiting_product)
    await message.answer("📝 Списание\nВведите ID товара из списка:\n\n" + "\n".join(f"{p.id} — {p.name}" for p in rows) + "\n\n/cancel — отмена")


@router.message(WriteoffState.waiting_product)
async def writeoff_product(message: Message, state: FSMContext):
    try:
        pid = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Введите числовой ID товара.")
        return
    async with SessionLocal() as session:
        product = (await session.execute(select(Product).where(Product.id == pid, Product.active.is_(True)))).scalar_one_or_none()
    if not product:
        await message.answer("❌ Товар не найден.")
        return
    await state.update_data(product_id=pid)
    await state.set_state(WriteoffState.waiting_quantity)
    await message.answer(f"Товар: {product.name}\nВведите количество для списания:")


@router.message(WriteoffState.waiting_quantity)
async def writeoff_quantity(message: Message, state: FSMContext):
    try:
        qty = Decimal((message.text or "").replace(",", ".").strip())
        if qty <= 0:
            raise ValueError
    except Exception:
        await message.answer("❌ Количество должно быть положительным числом.")
        return
    await state.update_data(quantity=str(qty))
    await state.set_state(WriteoffState.waiting_reason)
    await message.answer("Причина: напишите один вариант — порча / недостача / маркетинг / инвентаризация")


@router.message(WriteoffState.waiting_reason)
async def writeoff_reason(message: Message, state: FSMContext):
    reason = (message.text or "").strip()
    if not reason:
        await message.answer("❌ Укажите причину.")
        return
    await state.update_data(reason=reason)
    await state.set_state(WriteoffState.waiting_comment)
    await message.answer("Комментарий (можно написать «-»):")


@router.message(WriteoffState.waiting_comment)
async def writeoff_comment(message: Message, state: FSMContext):
    user = await access(message)
    if user is None:
        await state.clear()
        await message.answer("⛔ Доступ не настроен. Обратитесь к владельцу клуба.")
        return
    data = await state.get_data()
    async with SessionLocal() as session:
        employee = None
        if user.employee_id:
            employee = (await session.execute(select(Employee).where(Employee.id == user.employee_id))).scalar_one_or_none()
        club = (await session.execute(select(Club).where(Club.active.is_(True)).order_by(Club.id))).scalars().first()
        if not club:
            await state.clear()
            await message.answer("❌ Нет активного клуба. Сначала обновите бар и снеки.")
            return
        if employee is None:
            await state.clear()
            await message.answer("❌ Для списания Telegram должен быть привязан к сотруднику.")
            return
        reason = (await session.execute(select(WriteoffReason).where(WriteoffReason.name == data["reason"]))).scalar_one_or_none()
        if reason is None:
            reason = WriteoffReason(name=data["reason"])
            session.add(reason)
            await session.flush()
        writeoff = Writeoff(
            club_id=club.id,
            employee_id=employee.id,
            reason_id=reason.id,
            status=WriteoffStatus.PENDING.value,
            comment=message.text or None,
        )
        session.add(writeoff)
        await session.flush()
        session.add(WriteoffItem(writeoff_id=writeoff.id, product_id=int(data["product_id"]), quantity=abs(Decimal(data["quantity"]))))
        await session.commit()
    await state.clear()
    await message.answer("⏳ Списание создано и отправлено владельцу на согласование. Остаток пока не изменён.")


@router.message(F.text == "⏳ Списания на согласовании")
async def pending_writeoffs(message: Message):
    user = await access(message)
    if not user or user.role != UserRole.OWNER.value:
        await message.answer("⛔ Раздел доступен только владельца.")
        return
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(Writeoff, WriteoffItem, Product, Employee, WriteoffReason)
            .join(WriteoffItem, WriteoffItem.writeoff_id == Writeoff.id)
            .join(Product, Product.id == WriteoffItem.product_id)
            .outerjoin(Employee, Employee.id == Writeoff.employee_id)
            .join(WriteoffReason, WriteoffReason.id == Writeoff.reason_id)
            .where(Writeoff.status == WriteoffStatus.PENDING.value)
            .order_by(Writeoff.created_at)
            .limit(30)
        )).all()
    if not rows:
        await message.answer("⏳ Нет списаний на согласовании.")
        return
    lines = ["⏳ Списания на согласовании:"]
    for w, item, product, employee, reason in rows:
        who = employee.full_name if employee else "неизвестный сотрудник"
        lines.append(f"#{w.id} — {product.name} — {item.quantity:g} — {reason.name} — {who}")
    lines.append("\nДля согласования: /approve_writeoff ID")
    lines.append("Для отказа: /reject_writeoff ID")
    await message.answer("\n".join(lines))


async def _change_writeoff(message: Message, approve: bool):
    user = await access(message)
    if not user or user.role != UserRole.OWNER.value:
        await message.answer("⛔ Только владелец может согласовывать списания.")
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /approve_writeoff ID или /reject_writeoff ID")
        return
    wid = int(parts[1])
    async with SessionLocal() as session:
        writeoff = (await session.execute(select(Writeoff).where(Writeoff.id == wid))).scalar_one_or_none()
        if not writeoff:
            await message.answer("❌ Списание не найдено.")
            return
        if writeoff.status != WriteoffStatus.PENDING.value:
            await message.answer(f"Списание #{wid} уже имеет статус: {writeoff.status}.")
            return
        if approve:
            items = (await session.execute(select(WriteoffItem).where(WriteoffItem.writeoff_id == wid))).scalars().all()
            for item in items:
                balance = (await session.execute(select(InventoryBalance).where(
                    InventoryBalance.club_id == writeoff.club_id, InventoryBalance.product_id == item.product_id
                ))).scalar_one_or_none()
                if balance is None:
                    await message.answer("❌ Для товара нет остатка. Списание не согласовано.")
                    return
                if balance.quantity < item.quantity:
                    await message.answer(f"❌ Недостаточно остатка. Доступно: {balance.quantity:g}.")
                    return
            writeoff.status = WriteoffStatus.APPROVED.value
            writeoff.approved_by = message.from_user.id
            writeoff.approved_at = datetime.now(timezone.utc)
            for item in items:
                balance = (await session.execute(select(InventoryBalance).where(
                    InventoryBalance.club_id == writeoff.club_id, InventoryBalance.product_id == item.product_id
                ))).scalar_one()
                balance.quantity -= item.quantity
                session.add(InventoryOperation(
                    club_id=writeoff.club_id, product_id=item.product_id, employee_id=writeoff.employee_id, shift_id=writeoff.shift_id,
                    operation_type="writeoff", quantity=-item.quantity, source="writeoff", source_id=str(wid), comment=writeoff.comment
                ))
        else:
            writeoff.status = WriteoffStatus.REJECTED.value
            writeoff.approved_by = message.from_user.id
            writeoff.approved_at = datetime.now(timezone.utc)
        await session.commit()
        await write_audit(
            session, actor_telegram_id=message.from_user.id, action="writeoff_approved" if approve else "writeoff_rejected",
            entity_type="writeoff", entity_id=str(wid),
            payload={"status": "approved" if approve else "rejected", "employee_id": writeoff.employee_id, "shift_id": writeoff.shift_id},
        )
    await message.answer(("✅" if approve else "🚫") + f" Списание #{wid} " + ("согласовано." if approve else "отклонено."))


@router.message(Command("approve_writeoff"))
async def approve_writeoff(message: Message):
    await _change_writeoff(message, True)


@router.message(Command("reject_writeoff"))
async def reject_writeoff(message: Message):
    await _change_writeoff(message, False)

# --- Smart bar & snacks (v1.4) ---
class MinStockState(StatesGroup):
    waiting_value = State()


def _money(v: Decimal) -> str:
    return f"{v:,.2f}".replace(",", " ")


async def product_settings_text() -> str:
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(InventoryBalance, Product, Club)
            .join(Product, Product.id == InventoryBalance.product_id)
            .join(Club, Club.id == InventoryBalance.club_id)
            .where(Product.active.is_(True))
            .order_by(Club.name, Product.name)
        )).all()
    if not rows:
        return "🍔 <b>Настройки бара и снеков</b>\n\nНет данных. Сначала обновите остатки."
    lines = ["🍔 <b>Настройки бара и снеков</b>", "", "Минимальный остаток — порог, при котором товар считается требующим внимания.", ""]
    current = None
    for balance, product, club in rows:
        if club.name != current:
            current = club.name
            lines.append(f"🏢 <b>{club.name}</b>")
        status = "🔴" if balance.min_stock > 0 and balance.quantity <= balance.min_stock else ("🟡" if balance.min_stock > 0 and balance.quantity <= balance.min_stock * 1.5 else "🟢")
        lines.append(f"{status} {product.name}: остаток <b>{balance.quantity:g}</b> / минимум <b>{balance.min_stock:g}</b> — <code>{product.id}</code>")
    lines += ["", "Чтобы изменить порог: <code>/min_stock ID КОЛИЧЕСТВО</code>", "Например: <code>/min_stock 12 10</code>", "0 — отключить контроль минимума."]
    return "\n".join(lines)


@router.message(F.text == "⚙️ Минимальные остатки")
async def min_stock_menu(message: Message):
    user = await access(message)
    if user is None or user.role != UserRole.OWNER.value:
        await message.answer("⛔ Настройка минимальных остатков доступна только владельцу.")
        return
    await message.answer(await product_settings_text())


@router.message(Command("min_stock"))
async def min_stock_command(message: Message):
    user = await access(message)
    if user is None or user.role != UserRole.OWNER.value:
        await message.answer("⛔ Действие доступно только владельцу.")
        return
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer("Формат: /min_stock ID КОЛИЧЕСТВО\nПример: /min_stock 12 10")
        return
    try:
        product_id = int(parts[1])
        value = Decimal(parts[2].replace(",", "."))
        if value < 0:
            raise ValueError
    except Exception:
        await message.answer("❌ ID товара и количество должны быть корректными числами.")
        return
    async with SessionLocal() as session:
        product = (await session.execute(select(Product).where(Product.id == product_id))).scalar_one_or_none()
        if not product:
            await message.answer("❌ Товар не найден. Используйте ID из списка настроек.")
            return
        balances = (await session.execute(select(InventoryBalance).where(InventoryBalance.product_id == product_id))).scalars().all()
        if not balances:
            await message.answer("❌ Для этого товара ещё нет остатков. Сначала обновите данные.")
            return
        for balance in balances:
            balance.min_stock = value
        await session.commit()
        await write_audit(session, actor_telegram_id=message.from_user.id, action="inventory_min_stock_changed", entity_type="product", entity_id=str(product_id), payload={"min_stock": str(value)})
    await message.answer(f"✅ Для «{product.name}» минимальный остаток установлен: <b>{value:g}</b>.")


@router.message(F.text == "🔴 Критические остатки")
async def critical_stock(message: Message):
    user = await access(message)
    if user is None:
        await message.answer("⛔ Доступ не настроен.")
        return
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(InventoryBalance, Product, Club)
            .join(Product, Product.id == InventoryBalance.product_id)
            .join(Club, Club.id == InventoryBalance.club_id)
            .where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock)
            .order_by(InventoryBalance.quantity, Product.name)
        )).all()
    if not rows:
        await message.answer("🟢 Критических остатков нет.")
        return
    lines = ["🔴 <b>Критические остатки</b>", ""]
    for balance, product, club in rows:
        lines.append(f"🏢 {club.name}\n• {product.name}: <b>{balance.quantity:g}</b> из минимума <b>{balance.min_stock:g}</b>")
    await message.answer("\n".join(lines))


@router.message(F.text.regexp(r"^📊 Товары бара и снеков$"))
async def smart_products(message: Message):
    user = await access(message)
    if user is None:
        await message.answer("⛔ Доступ не настроен.")
        return
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=30)
    try:
        result = await langame.product_sales(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"), page=1, page_limit=500)
        rows = result.get("data") or []
    except Exception as exc:
        await message.answer(f"❌ Не удалось получить продажи: {str(exc)[:400]}")
        return
    stats = {}
    for row in rows:
        if row.get("cancel"):
            continue
        pid = row.get("list_goods_id") or row.get("product_id") or row.get("id")
        name = row.get("name") or row.get("product_name") or f"Товар #{pid or '—'}"
        qty = _num(row.get("count", row.get("quantity", 0)))
        sale = _num(row.get("price_sale", row.get("sum", row.get("amount", 0))))
        purchase = _num(row.get("price_purchase", 0))
        # If the endpoint returns unit prices, multiply by quantity; otherwise use amount as-is.
        revenue = sale * qty if row.get("price_sale") is not None else sale
        cost = purchase * qty
        key = str(pid or name)
        item = stats.setdefault(key, {"name": name, "qty": Decimal(0), "revenue": Decimal(0), "cost": Decimal(0)})
        item["qty"] += qty; item["revenue"] += revenue; item["cost"] += cost
    if not stats:
        await message.answer("📊 За последние 30 дней продаж не найдено.")
        return
    top = sorted(stats.values(), key=lambda x: x["revenue"], reverse=True)[:25]
    lines = ["📊 <b>Товары бара и снеков за 30 дней</b>", ""]
    for i, item in enumerate(top, 1):
        if item["cost"] > 0:
            margin = item["revenue"] - item["cost"]
            margin_pct = (margin / item["revenue"] * 100) if item["revenue"] else Decimal(0)
            margin_line = f"Маржа: {_money(margin)} ₽ ({margin_pct:.1f}%)"
        else:
            margin_line = "Маржа: — (нет данных о закупочной цене)"
        lines.append(f"{i}. <b>{item['name']}</b>\n   Продано: {item['qty']:g} · Выручка: {_money(item['revenue'])} ₽\n   {margin_line}")
    await message.answer("\n".join(lines))
