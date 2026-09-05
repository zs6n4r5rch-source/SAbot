from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


def _btn(text: str, callback: str):
    return InlineKeyboardButton(text=text, callback_data=callback)


def owner_inline_menu(mini_app_url: str | None = None):
    rows = [
        [_btn("👥 Администраторы", "owner:admins"), _btn("👥 Клиенты", "owner:clients")],
        [_btn("💰 Финансы", "owner:finance"), _btn("📈 Аналитика", "owner:analytics")],
        [_btn("🍔 Бар и снеки", "owner:inventory"), _btn("🏆 Бонусы", "owner:bonuses")],
        [_btn("⚠️ Нарушения", "owner:penalties"), _btn("🔔 Требует внимания", "owner:attention")],
        [_btn("📣 Рассылки", "owner:broadcast"), _btn("⚙️ Настройки", "owner:settings")],
        [_btn("🔄 Перезапустить бота", "system:restart")],
    ]
    if mini_app_url:
        base = mini_app_url.rstrip("/")
        rows.insert(0, [InlineKeyboardButton(text="📣 Рассылки · Telegram / SMS / Email", web_app=WebAppInfo(url=base + "/static/broadcasts.html"))])
        rows.insert(1, [InlineKeyboardButton(text="📊 Статистика · все данные", web_app=WebAppInfo(url=base + "/static/statistics.html"))])
        rows.insert(2, [InlineKeyboardButton(text="👥 Клиенты · сегменты и решения", web_app=WebAppInfo(url=base + "/static/guests.html"))])
        rows.insert(3, [InlineKeyboardButton(text="📱 Соцсети · SMM аналитика", web_app=WebAppInfo(url=base + "/static/social.html"))])
        rows.insert(4, [InlineKeyboardButton(text="📣 Реклама · рекомендации", web_app=WebAppInfo(url=base + "/static/advertising.html"))])
        rows.insert(5, [InlineKeyboardButton(text="🚀 Открыть Strike Arena", web_app=WebAppInfo(url=base))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_inline_menu(mini_app_url: str | None = None):
    rows = [
        [_btn("🍔 Бар и снеки", "admin:inventory"), _btn("📋 Мои смены", "admin:shifts")],
        [_btn("📊 Моя статистика", "admin:stats"), _btn("💰 Моя зарплата", "admin:salary")],
        [_btn("🏆 Мои бонусы", "admin:bonuses"), _btn("🔒 Закрыть смену", "admin:close_shift")],
    ]
    if mini_app_url:
        rows.insert(0, [InlineKeyboardButton(text="🚀 Открыть Strike Arena", web_app=WebAppInfo(url=mini_app_url))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_inline(callback: str = "nav:owner"):
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("↩️ Назад", callback)]])