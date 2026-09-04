from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from sqlalchemy import select, func

from app.db.session import SessionLocal

from app.models import (
    TelegramUser,
    UserRole,
    Shift,
    Writeoff,
    WriteoffStatus,
    Discrepancy,
    DiscrepancyStatus,
    InventoryBalance,
    ShiftCloseReport,
    ShiftCloseReportStatus,
)

from app.bot.analytics import sales_totals


router = Router()



def dashboard_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Полный отчёт",
                    callback_data="dashboard:report",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚠️ Требует внимания",
                    callback_data="dashboard:attention",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔎 Контроль администраторов",
                    callback_data="integrity:30",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data="dashboard:refresh",
                )
            ],
        ]
    )



async def is_owner(uid: int | None):

    if uid is None:
        return False


    async with SessionLocal() as session:

        user = (
            await session.execute(
                select(TelegramUser).where(
                    TelegramUser.telegram_id == uid
                )
            )
        ).scalar_one_or_none()


    return bool(
        user
        and user.active
        and user.role == UserRole.OWNER.value
    )



async def metrics():

    now = datetime.now(timezone.utc)

    day_start = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )



    sales, units, _ = await sales_totals(
        day_start,
        now,
    )



    async with SessionLocal() as session:

        open_shifts = await session.scalar(
            select(
                func.count(
                    Shift.id
                )
            )
            .where(
                Shift.ended_at.is_(None)
            )
        )


        pending_writeoffs = await session.scalar(
            select(
                func.count(
                    Writeoff.id
                )
            )
            .where(
                Writeoff.status ==
                WriteoffStatus.PENDING.value
            )
        )


        discrepancies = await session.scalar(
            select(
                func.count(
                    Discrepancy.id
                )
            )
            .where(
                Discrepancy.status !=
                DiscrepancyStatus.RESOLVED.value
            )
        )


        critical_stock = await session.scalar(
            select(
                func.count(
                    InventoryBalance.id
                )
            )
            .where(
                InventoryBalance.min_stock > 0,
                InventoryBalance.quantity <=
                InventoryBalance.min_stock,
            )
        )


        close_reports = await session.scalar(
            select(
                func.count(
                    ShiftCloseReport.id
                )
            )
            .where(
                ShiftCloseReport.status !=
                ShiftCloseReportStatus.SUBMITTED.value
            )
        )


    return {
        "sales": sales,
        "units": units,
        "open_shifts": open_shifts or 0,
        "pending_writeoffs": pending_writeoffs or 0,
        "discrepancies": discrepancies or 0,
        "critical_stock": critical_stock or 0,
        "close_reports": close_reports or 0,
    }



async def dashboard_text():

    m = await metrics()


    attention = (
        m["pending_writeoffs"]
        +
        m["discrepancies"]
        +
        m["critical_stock"]
        +
        m["close_reports"]
    )


    return (
        "📅 <b>Ежедневная сводка</b>\n\n"
        f"📅 {datetime.now():%d.%m.%Y}\n\n"

        f"💰 Продажи бара и снеков: "
        f"<b>{m['sales']:.2f} ₽</b>\n"

        f"📦 Продано единиц: "
        f"<b>{m['units']:g}</b>\n"

        f"🟢 Открытых смен: "
        f"<b>{m['open_shifts']}</b>\n"

        f"⚠️ Критические остатки: "
        f"<b>{m['critical_stock']}</b>\n"

        f"📋 Списания ожидают: "
        f"<b>{m['pending_writeoffs']}</b>\n"

        f"⚠️ Расхождения: "
        f"<b>{m['discrepancies']}</b>\n"

        f"📄 Отчёты закрытия смен: "
        f"<b>{m['close_reports']}</b>\n\n"

        f"🔔 <b>Требует внимания: {attention}</b>"
    )



async def attention_text():

    m = await metrics()

    return (
        "🔔 <b>Требует внимания</b>\n\n"
        f"⚠️ Критические остатки: <b>{m['critical_stock']}</b>\n"
        f"📋 Списания ожидают: <b>{m['pending_writeoffs']}</b>\n"
        f"⚠️ Расхождения: <b>{m['discrepancies']}</b>\n"
        f"📄 Отчёты закрытия смен: <b>{m['close_reports']}</b>"
    )
