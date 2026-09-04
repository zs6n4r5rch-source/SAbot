import asyncio
import os

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.services.auth import get_access
from app.models import UserRole

router = Router()


async def _owner(message: Message) -> bool:
    user = await get_access(message)
    return bool(user and user.active and user.role == UserRole.OWNER.value)


async def _stop_process():
    await asyncio.sleep(1.0)
    os._exit(0)


@router.callback_query(F.data == "system:restart")
async def restart_callback(callback: CallbackQuery):
    if not callback.message or not await _owner(callback.message):
        await callback.answer("⛔ Только для владельца.", show_alert=True)
        return
    await callback.answer("Перезапускаю…")
    await callback.message.answer("♻️ Перезапуск бота запущен. Через несколько секунд бот вернётся в сеть.")
    asyncio.create_task(_stop_process())


@router.message(Command("restart"))
async def restart_command(message: Message):
    if not await _owner(message):
        await message.answer("⛔ Только для владельца.")
        return
    await message.answer("♻️ Перезапуск бота запущен. Через несколько секунд бот вернётся в сеть.")
    asyncio.create_task(_stop_process())
