from aiogram import BaseMiddleware
from aiogram.types import Message


# Navigation buttons must never be consumed as input for an unfinished form.
# This prevents stale FSM states from turning menu clicks into numeric/text errors.
MENU_TEXTS = {
    "📅 Ежедневная сводка",
    "👥 Администраторы",
    "👥 Клиенты",
    "🍔 Бар и снеки",
    "📊 Аналитика",
    "💰 Финансы",
    "🏆 Бонусы",
    "🔔 Внимание",
    "🔔 Требует внимания",
    "📣 Рассылки",
    "⚙️ Настройки",
    "🔄 Синхронизировать LANGAME",
    "👤 Список администраторов",
    "🔗 Заявки на привязку",
    "🔗 Привязать Telegram",
    "💰 Зарплата",
    "⚠️ Штрафы",
    "⚠️ Нарушения",
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
}


class MenuStateResetMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and (event.text or "").strip() in MENU_TEXTS:
            state = data.get("state")
            if state is not None:
                await state.clear()
        return await handler(event, data)
