from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
)



def admin_menu():

    return ReplyKeyboardMarkup(
        keyboard=[
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
        ],
        resize_keyboard=True,
    )



def owner_menu():

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="👑 Панель владельца"),
                KeyboardButton(text="👥 Администраторы"),
            ],
            [
                KeyboardButton(text="🍔 Бар и снеки"),
                KeyboardButton(text="📊 Аналитика"),
            ],
            [
                KeyboardButton(text="💰 Финансы"),
                KeyboardButton(text="🏆 Бонусы"),
            ],
            [
                KeyboardButton(text="🔔 Требует внимания"),
            ],
            [
                KeyboardButton(text="👥 Клиенты"),
                KeyboardButton(text="📣 Рассылки"),
            ],
            [
                KeyboardButton(text="⚙️ Настройки"),
            ],
        ],
        resize_keyboard=True,
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