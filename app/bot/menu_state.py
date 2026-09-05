from aiogram import BaseMiddleware
from aiogram.types import Message


# Menu actions must always be navigation, never be consumed as input for a
# previously started form (inventory count, write-off, owner report setup, etc.).
MENU_TEXTS = {
    "📅 Ежедневная сводка",
    "👥 Администраторы",
    "🍔 Бар и снеки",
    "📊 Аналитика",
    "💰 Финансы",
    "🏆 Бонусы",
    "🔔 Требует внимания",
    "👥 Клиенты",
    "📣 Рассылки",
    "⚙️ Настройки",
    "🔄 Синхронизировать LANGAME",
    "👤 Список администраторов",
    "🔗 Заявки на привязку",
    "🔗 Привязать Telegram",
    "💰 Зарплата",
    "⚠️ Штрафы",
    "🏆 Рейтинг администраторов",
    "🔎 Контроль администраторов",
    "📊 Ежедневный отчёт",
    "🍔 Настройки бара и снеков",
    "👤 Управление администраторами",
    "➕ Добавить владельца",
    "📦 Остатки",
    "📥 Приходы",
    "🔴 Критические остатки",
    "📊 Товары бара и снеков",
    "📈 Продажи бара и снеков",
    "📋 Списание",
    "⏳ Списания на согласовании",
    "🧮 Инвентаризации",
    "⚠️ Расхождения",
    "⚙️ Минимальные остатки",
    "📜 История бара и снеков",
    "🔄 Обновить остатки",
    "➕ Новая рассылка",
    "🎯 Аудитории",
    "📜 История",
    "📊 Статистика рассылок",
    "↩️ Назад",
    "🍔 Настройки бара и снеков",
}


class MenuStateResetMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and (event.text or "").strip() in MENU_TEXTS:
            state = data.get("state")
            if state is not None:
                await state.clear()
        return await handler(event, data)
