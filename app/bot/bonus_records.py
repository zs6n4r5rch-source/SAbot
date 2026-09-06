from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import SalaryPeriod, UserRole
from app.services.auth import get_access
from app.services.bonus_records import sync_salary_adjustments_to_bonus_records

router = Router()


@router.message(Command("sync_bonus_records"))
async def sync_bonus_records(message: Message):
    user = await get_access(message)
    if user is None or user.role != UserRole.OWNER.value:
        await message.answer("⛔ Только владелец.")
        return

    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /sync_bonus_records PERIOD_ID")
        return

    period_id = int(parts[1])
    async with SessionLocal() as session:
        period = await session.get(SalaryPeriod, period_id)
        if period is None:
            await message.answer("❌ Период не найден.")
            return
        created, skipped = await sync_salary_adjustments_to_bonus_records(session, period)
        await session.commit()

    await message.answer(
        f"✅ Бонусы синхронизированы для периода #{period_id}.\n"
        f"Создано записей: {created}\n"
        f"Уже существовало: {skipped}"
    )
