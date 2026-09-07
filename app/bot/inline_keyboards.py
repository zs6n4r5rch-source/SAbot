from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


def _btn(text: str, callback: str):
    return InlineKeyboardButton(text=text, callback_data=callback)


def owner_inline_menu(mini_app_url: str | None = None):
    """Primary owner menu shown directly under the bot message.

    Keep callback data stable because existing owner handlers route by it.
    """
    rows = [
        [_btn("📅 Ежедневная сводка", "owner:dashboard"), _btn("🔔 Требует внимания", "owner:attention")],
        [_btn("📊 Аналитика", "owner:analytics"), _btn("💰 Финансы", "owner:finance")],
        [_btn("🍔 Бар и снеки", "owner:inventory"), _btn("👥 Клиенты", "owner:clients")],
        [_btn("👥 Администраторы", "owner:admins"), _btn("🏆 Бонусы", "owner:bonuses")],
        [_btn("📣 Рассылки", "owner:broadcast"), _btn("⚙️ Настройки", "owner:settings")],
    ]
    if mini_app_url:
        base = mini_app_url.rstrip("/")
        rows.insert(0, [
            InlineKeyboardButton(text="🚀 Открыть Strike Arena", web_app=WebAppInfo(url=base))
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_inline_menu(mini_app_url: str | None = None):
    rows = [
        [_btn("🍔 Бар и снеки", "admin:inventory"), _btn("📋 Мои смены", "admin:shifts")],
        [_btn("📊 Моя статистика", "admin:stats"), _btn("💰 Моя зарплата", "admin:salary")],
        [_btn("🏆 Мои бонусы", "admin:bonuses"), _btn("🔒 Закрыть смену", "admin:close_shift")],
    ]
    if mini_app_url:
        base = mini_app_url.rstrip("/")
        rows.insert(0, [InlineKeyboardButton(text="🚀 Открыть Strike Arena", web_app=WebAppInfo(url=base))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_inline(callback: str = "nav:owner"):
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("↩️ Назад", callback)]])
