from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
)


def admin_menu(mini_app_url: str | None = None):
    rows = [
        [
            KeyboardButton(text="🍔 Бар и снеки"),
            KeyboardButton(text="📋 Мои смены"),
        ],
        [
            KeyboardButton(text="🔒 Закрыть смену"),
        ],
        [
            KeyboardButton(text="📊 Моя статистика"),
            KeyboardButton(text="💰 Моя зарплата"),
        ],
        [
            KeyboardButton(text="🏆 Мои бонусы"),
        ],
    ]
    if mini_app_url:
        rows.insert(0, [
            KeyboardButton(
                text="🚀 Открыть Strike Arena",
                web_app=WebAppInfo(url=mini_app_url.rstrip("/")),
            )
        ])

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите раздел",
    )


def owner_menu(mini_app_url: str | None = None):
    """Primary Telegram-native owner navigation.

    Keep button texts stable: handlers route owner actions by exact text.
    The Mini App is deliberately the first, full-width action; operational
    sections remain available as native Telegram buttons below it.
    """
    rows = [
        [
            KeyboardButton(text="📅 Ежедневная сводка"),
            KeyboardButton(text="🔔 Требует внимания"),
        ],
        [
            KeyboardButton(text="📊 Аналитика"),
            KeyboardButton(text="💰 Финансы"),
        ],
        [
            KeyboardButton(text="🍔 Бар и снеки"),
            KeyboardButton(text="👥 Клиенты"),
        ],
        [
            KeyboardButton(text="👥 Администраторы"),
            KeyboardButton(text="🏆 Бонусы"),
        ],
        [
            KeyboardButton(text="📣 Рассылки"),
            KeyboardButton(text="⚙️ Настройки"),
        ],
    ]

    if mini_app_url:
        rows.insert(0, [
            KeyboardButton(
                text="🚀 Открыть Strike Arena",
                web_app=WebAppInfo(url=mini_app_url.rstrip("/")),
            )
        ])

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Панель владельца · выберите раздел",
    )


def clients_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔎 Поиск"),
                KeyboardButton(text="📋 Все клиенты"),
            ],
            [
                KeyboardButton(text="🏷 Группы лояльности"),
                KeyboardButton(text="💬 Telegram"),
            ],
            [
                KeyboardButton(text="📊 Статистика клиентов"),
                KeyboardButton(text="↩️ Назад"),
            ],
        ],
        resize_keyboard=True,
    )


def mailing_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="➕ Новая рассылка"),
                KeyboardButton(text="🎯 Аудитории"),
            ],
            [
                KeyboardButton(text="📜 История"),
            ],
            [
                KeyboardButton(text="📊 Статистика рассылок"),
                KeyboardButton(text="↩️ Назад"),
            ],
        ],
        resize_keyboard=True,
    )


def owner_settings_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Ежедневный отчёт"),
            ],
            [
                KeyboardButton(text="🍔 Настройки бара и снеков"),
            ],
            [
                KeyboardButton(text="👤 Управление администраторами"),
            ],
            [
                KeyboardButton(text="➕ Добавить владельца"),
            ],
            [
                KeyboardButton(text="↩️ Назад"),
            ],
        ],
        resize_keyboard=True,
    )


def admins_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔄 Синхронизировать LANGAME"),
            ],
            [
                KeyboardButton(text="👤 Список администраторов"),
                KeyboardButton(text="🔗 Заявки на привязку"),
            ],
            [
                KeyboardButton(text="🔗 Привязать Telegram"),
            ],
            [
                KeyboardButton(text="💰 Зарплата"),
                KeyboardButton(text="⚠️ Штрафы"),
            ],
            [
                KeyboardButton(text="🏆 Рейтинг администраторов"),
            ],
            [
                KeyboardButton(text="🔎 Контроль администраторов"),
            ],
            [
                KeyboardButton(text="↩️ Назад"),
            ],
        ],
        resize_keyboard=True,
    )


def inventory_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔄 Обновить остатки"),
            ],
            [
                KeyboardButton(text="📦 Остатки"),
                KeyboardButton(text="📥 Приходы"),
            ],
            [
                KeyboardButton(text="🔴 Критические остатки"),
                KeyboardButton(text="📊 Товары бара и снеков"),
            ],
            [
                KeyboardButton(text="📈 Продажи бара и снеков"),
                KeyboardButton(text="📋 Списание"),
            ],
            [
                KeyboardButton(text="⏳ Списания на согласовании"),
            ],
            [
                KeyboardButton(text="🧮 Инвентаризации"),
                KeyboardButton(text="⚠️ Расхождения"),
            ],
            [
                KeyboardButton(text="⚙️ Минимальные остатки"),
                KeyboardButton(text="📜 История бара и снеков"),
            ],
            [
                KeyboardButton(text="↩️ Назад"),
            ],
        ],
        resize_keyboard=True,
    )
