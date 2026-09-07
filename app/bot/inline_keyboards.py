from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


def _btn(text: str, callback: str):
    return InlineKeyboardButton(text=text, callback_data=callback)


def owner_inline_menu(mini_app_url: str | None = None):
    """Compact Telegram entry point for the Strike Arena owner console.

    Telegram inline keyboards cannot carry the Mini App's custom visual theme,
    so the chat UI stays intentionally compact while the branded experience is
    opened with the primary Web App button.
    """
    rows = []
    if mini_app_url:
        base = mini_app_url.rstrip("/")
        rows.append([
            InlineKeyboardButton(
                text="🚀 Открыть STRIKE ARENA",
                web_app=WebAppInfo(url=base),
            )
        ])

    rows.extend([
        [_btn("📅 Сводка", "owner:dashboard"), _btn("🔔 Требует внимания", "owner:attention")],
        [_btn("📊 Аналитика", "owner:analytics"), _btn("💰 Финансы", "owner:finance")],
        [_btn("🍔 Бар и снеки", "owner:inventory"), _btn("👥 Клиенты", "owner:clients")],
        [_btn("👥 Администраторы", "owner:admins"), _btn("🏆 Бонусы", "owner:bonuses")],
        [_btn("📣 Рассылки", "owner:broadcast"), _btn("⚙️ Настройки", "owner:settings")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_inline_menu(mini_app_url: str | None = None):
    rows = []
    if mini_app_url:
        base = mini_app_url.rstrip("/")
        rows.append([
            InlineKeyboardButton(
                text="🚀 Открыть STRIKE ARENA",
                web_app=WebAppInfo(url=base),
            )
        ])
    rows.extend([
        [_btn("🍔 Бар и снеки", "admin:inventory"), _btn("📋 Мои смены", "admin:shifts")],
        [_btn("📊 Моя статистика", "admin:stats"), _btn("💰 Моя зарплата", "admin:salary")],
        [_btn("🏆 Мои бонусы", "admin:bonuses"), _btn("🔒 Закрыть смену", "admin:close_shift")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_inline(callback: str = "nav:owner"):
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("↩️ Назад", callback)]])
