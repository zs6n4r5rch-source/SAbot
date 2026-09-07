from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


def _btn(text: str, callback: str):
    return InlineKeyboardButton(text=text, callback_data=callback)


def owner_inline_menu(mini_app_url: str | None = None):
    """Compact Telegram launcher for the Strike Arena owner console.

    Telegram chat buttons cannot reproduce the Mini App's custom visual theme.
    The owner chat therefore exposes one clear entry point; the full owner
    navigation lives inside the branded Strike Arena Mini App.
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
    else:
        rows.append([_btn("📊 Открыть панель владельца", "owner:dashboard")])
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
