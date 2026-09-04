from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select, func

from app.bot.keyboards import (
    admin_menu,
    owner_menu,
    admins_menu,
    owner_settings_menu,
)

from app.db.session import SessionLocal

from app.models import (
    Employee,
    TelegramUser,
    UserRole,
    Shift,
    Club,
    Writeoff,
    WriteoffItem,
    WriteoffStatus,
    Discrepancy,
    SalaryPeriod,
)

from app.services.auth import (
    get_access,
)
from app.services.langame import langame_client
from app.services.staff_access import match_admin_profiles_to_employees


router = Router()

# ReplyKeyboard владельца. Telegram присылает нажатие такой кнопки
# как обычное Message с точным текстом кнопки. Чтобы порядок подключённых
# дочерних роутеров не влиял на работу меню, все кнопки OWNER маршрутизируем
# из одного обработчика основного router.
from app.bot.inline_keyboards import admin_inline_menu, owner_inline_menu

from app.bot.owner_dashboard import (
    dashboard_text,
    dashboard_keyboard,
    is_owner as owner_dashboard_is_owner,
)


OWNER_MENU_BUTTONS = {
    "👑 Панель владельца",
    "👥 Администраторы",
    "🍔 Бар и снеки",
    "📊 Аналитика",
    "💰 Финансы",
    "🏆 Бонусы",
    "🔔 Требует внимания",
    "👥 Клиенты",
    "📣 Рассылки",
    "⚙️ Настройки",
}


@router.callback_query(F.data.startswith("owner:"))
async def owner_callback_dispatch(callback: CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    if not await is_owner(callback.message):
        await callback.answer("⛔ Только для владельца.", show_alert=True)
        return
    await callback.answer()
    action = callback.data.split(":", 1)[1]
    message = callback.message
    if action == "dashboard":
        await message.edit_text(await dashboard_text(), reply_markup=owner_inline_menu(settings.mini_app_url or None))
    elif action == "admins":
        await admins(message)
    elif action == "inventory":
        from app.bot.inventory import inventory_menu_handler
        await inventory_menu_handler(message)
    elif action == "analytics":
        from app.bot.analytics import analytics_menu
        await analytics_menu(message)
    elif action == "finance":
        from app.bot.finance import finance_button
        await finance_button(message)
    elif action == "bonuses":
        from app.bot.salary import owner_bonuses_view
        await owner_bonuses_view(message)
    elif action == "attention":
        from app.bot.owner_dashboard import attention_button
        await attention_button(message)
    elif action == "clients":
        from app.bot.clients import clients
        await clients(message)
    elif action == "broadcast":
        from app.bot.mailing import mailings
        await mailings(message)
    elif action == "settings":
        await settings_menu(message)
    elif action == "penalties":
        from app.bot.penalties import penalties_menu
        await penalties_menu(message)


@router.callback_query(F.data.startswith("admin:"))
async def admin_callback_dispatch(callback: CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user = await get_access(callback.message)
    if not user or user.role != UserRole.ADMIN.value:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await callback.answer()
    message = callback.message
    action = callback.data.split(":", 1)[1]
    if action == "inventory":
        from app.bot.inventory import inventory_menu_handler
        await inventory_menu_handler(message)
    elif action == "shifts":
        await my_shifts(message)
    elif action == "stats":
        await my_stats(message)
    elif action == "salary":
        from app.bot.salary import my_salary_view
        await my_salary_view(message)
    elif action == "bonuses":
        from app.bot.salary import my_bonuses_view
        await my_bonuses_view(message)
    elif action == "close_shift":
        await message.answer("🔒 Для закрытия смены используйте кнопку «🔒 Закрыть смену» в рабочем меню.")


@router.callback_query(F.data == "nav:owner")
async def owner_back_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    if not await is_owner(callback.message):
        await callback.answer("⛔ Только для владельца.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(await dashboard_text(), reply_markup=owner_inline_menu(settings.mini_app_url or None))


@router.message(F.text.in_(OWNER_MENU_BUTTONS))
async def owner_menu_dispatch(message: Message):
    if not await is_owner(message):
        await message.answer("⛔ Только для владельца.")
        return

    text = (message.text or "").strip()

    if text == "👑 Панель владельца":
        await message.answer(
            await dashboard_text(),
            reply_markup=dashboard_keyboard(),
        )
        return

    if text == "👥 Администраторы":
        await admins(message)
        return

    if text == "🍔 Бар и снеки":
        from app.bot.inventory import inventory_menu_handler
        await inventory_menu_handler(message)
        return

    if text == "📊 Аналитика":
        from app.bot.analytics import analytics_menu
        await analytics_menu(message)
        return

    if text == "💰 Финансы":
        from app.bot.finance import finance_button
        await finance_button(message)
        return

    if text == "🏆 Бонусы":
        from app.bot.salary import owner_bonuses_view
        await owner_bonuses_view(message)
        return

    if text == "🔔 Требует внимания":
        from app.bot.owner_dashboard import attention_button
        await attention_button(message)
        return

    if text == "👥 Клиенты":
        from app.bot.clients import clients
        await clients(message)
        return

    if text == "📣 Рассылки":
        from app.bot.mailing import mailings
        await mailings(message)
        return

    if text == "⚙️ Настройки":
        await settings_menu(message)
        return


langame = langame_client



# подключение модулей
from app.bot.inventory import router as inventory_router
router.include_router(inventory_router)

from app.bot.salary import router as salary_router
router.include_router(salary_router)

from app.bot.guest import router as guest_router
router.include_router(guest_router)

from app.bot.admin_profiles import router as admin_profiles_router
router.include_router(admin_profiles_router)

from app.bot.integrity import router as integrity_router
router.include_router(integrity_router)

from app.bot.penalties import router as penalties_router
router.include_router(penalties_router)

from app.bot.clients import router as clients_router
router.include_router(clients_router)

from app.bot.analytics import router as analytics_router
router.include_router(analytics_router)

from app.bot.finance import router as finance_router
router.include_router(finance_router)

from app.bot.mailing import router as mailing_router
router.include_router(mailing_router)

from app.bot.admin_settings import router as admin_settings_router
router.include_router(admin_settings_router)

from app.bot.staff_binding import router as staff_binding_router
router.include_router(staff_binding_router)

from app.bot.owner_settings import router as owner_settings_router
router.include_router(owner_settings_router)

from app.bot.owner_dashboard import router as owner_dashboard_router
router.include_router(owner_dashboard_router)



class AdminLinkState(StatesGroup):

    waiting_telegram_id = State()

    waiting_employee_id = State()


@router.message(Command("cancel"), AdminLinkState.waiting_telegram_id)
@router.message(Command("cancel"), AdminLinkState.waiting_employee_id)
async def cancel_link(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Операция отменена.")




async def is_owner(message: Message):

    user = await get_access(message)

    return bool(
        user and
        user.role == UserRole.OWNER.value
    )



async def deny(message: Message):

    await message.answer(
        "⛔ Доступ не настроен.\n"
        "Обратитесь к владельцу клуба."
    )



@router.message(Command("myid"))
async def my_id(message: Message):

    if not message.from_user:
        return

    await message.answer(
        f"Ваш Telegram ID:\n"
        f"<code>{message.from_user.id}</code>"
    )



@router.message(CommandStart())
async def start(message: Message):

    from app.bot.staff_binding import process_staff_start


    if await process_staff_start(message):
        return



    args = (
        message.text or ""
    ).split(maxsplit=1)



    if (
        len(args) == 2 and
        args[1].startswith("guest_")
    ):

        from app.bot.guest import process_invite

        await process_invite(
            message,
            args[1][6:]
        )

        return



    user = await get_access(message)



    if user is None:

        await deny(message)

        return



    if user.role == UserRole.OWNER.value:

        from app.bot.owner_dashboard import dashboard_text

        await message.answer(
            await dashboard_text(),
            reply_markup=owner_inline_menu(settings.mini_app_url or None)
        )

    else:

        await message.answer(
            "Добро пожаловать, Administrator.",
            reply_markup=admin_inline_menu(settings.mini_app_url or None)
        )



@router.message(F.text == "📋 Мои смены")
async def my_shifts(message: Message):

    user = await get_access(message)


    if user is None:

        await deny(message)

        return



    if user.employee_id is None:

        await message.answer(
            "⚠️ Ваш Telegram не привязан к администратору."
        )

        return



    end = datetime.now(timezone.utc)

    start = end - timedelta(days=30)



    async with SessionLocal() as session:

        rows = (
            await session.execute(
                select(
                    Shift,
                    Club
                )
                .join(
                    Club,
                    Club.id == Shift.club_id
                )
                .where(
                    Shift.employee_id == user.employee_id,
                    Shift.started_at >= start,
                    Shift.started_at <= end,
                )
                .order_by(
                    Shift.started_at.desc()
                )
                .limit(50)
            )
        ).all()



    if not rows:

        await message.answer(
            "📋 Мои смены\n\n"
            "За последние 30 дней смен нет."
        )

        return



    total = Decimal("0")

    lines = [
        "📋 <b>Мои смены</b>",
        "Период: последние 30 дней",
        "",
    ]



    for shift, club in rows:

        hours = Decimal("0")


        if shift.ended_at:

            hours = Decimal(
                str(
                    (
                        shift.ended_at -
                        shift.started_at
                    ).total_seconds()
                )
            ) / Decimal("3600")



        total += hours


        end_text = (
            shift.ended_at.strftime("%d.%m %H:%M")
            if shift.ended_at
            else "открыта"
        )


        lines.append(
            f"• {shift.started_at:%d.%m %H:%M} "
            f"— {end_text} "
            f"· {club.name} "
            f"· {hours:.1f} ч"
        )



    lines += [
        "",
        f"Смен: <b>{len(rows)}</b>",
        f"Отработано: <b>{total:.1f} ч</b>",
    ]



    await message.answer(
        "\n".join(lines)
    )

@router.message(F.text == "📊 Моя статистика")
async def my_stats(message: Message):

    user = await get_access(message)

    if user is None:
        await deny(message)
        return


    if user.employee_id is None:

        await message.answer(
            "⚠️ Ваш Telegram не привязан к администратору."
        )

        return



    from app.bot.analytics import sales_rows


    end = datetime.now(timezone.utc)

    start = end - timedelta(days=30)



    async with SessionLocal() as session:

        shifts = (
            await session.execute(
                select(Shift).where(
                    Shift.employee_id == user.employee_id,
                    Shift.started_at >= start,
                    Shift.started_at <= end,
                )
            )
        ).scalars().all()



        writeoffs = await session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        WriteoffItem.quantity
                    ),
                    0,
                )
            )
            .join(
                Writeoff,
                Writeoff.id ==
                WriteoffItem.writeoff_id
            )
            .where(
                Writeoff.employee_id ==
                user.employee_id,
                Writeoff.created_at >= start,
                Writeoff.created_at <= end,
                Writeoff.status ==
                WriteoffStatus.APPROVED.value,
            )
        ) or 0



        discrepancies = await session.scalar(
            select(
                func.count(
                    Discrepancy.id
                )
            )
            .where(
                Discrepancy.employee_id ==
                user.employee_id,
                Discrepancy.created_at >= start,
                Discrepancy.created_at <= end,
            )
        ) or 0



        periods = (
            await session.execute(
                select(SalaryPeriod).where(
                    SalaryPeriod.employee_id ==
                    user.employee_id,
                    SalaryPeriod.date_from <=
                    end.date(),
                    SalaryPeriod.date_to >=
                    start.date(),
                )
            )
        ).scalars().all()



    sales = Decimal("0")
    units = Decimal("0")

    shift_ids = {
        int(x.langame_shift_id)
        for x in shifts
        if x.langame_shift_id
    }


    try:

        for row in await sales_rows(start, end):

            if (
                int(row.get("cancel", 0) or 0)
                == 1
            ):
                continue


            if row.get("working_shift_id") is None:
                continue


            if int(row["working_shift_id"]) not in shift_ids:
                continue


            qty = Decimal(
                str(
                    row.get(
                        "count",
                        0
                    )
                )
            )


            sales += (
                Decimal(
                    str(
                        row.get(
                            "price_sale",
                            0
                        )
                    )
                )
                *
                qty
            )


            units += qty


    except Exception:

        pass



    hours = Decimal("0")


    for shift in shifts:

        if shift.ended_at:

            hours += Decimal(
                str(
                    (
                        shift.ended_at -
                        shift.started_at
                    ).total_seconds()
                )
            ) / Decimal("3600")



    salary = sum(
        (
            Decimal(
                str(
                    x.total_amount or 0
                )
            )
            for x in periods
        ),
        Decimal("0"),
    )



    await message.answer(
        "📊 <b>Моя статистика</b>\n\n"
        f"Смен: <b>{len(shifts)}</b>\n"
        f"Отработано: <b>{hours:.1f} ч</b>\n"
        f"Продажи: <b>{sales:.2f} ₽</b>\n"
        f"Продано единиц: <b>{units:g}</b>\n"
        f"Списания: <b>{Decimal(str(writeoffs)):g}</b>\n"
        f"Расхождения: <b>{discrepancies}</b>\n"
        f"Зарплата: <b>{salary:.2f} ₽</b>"
    )



@router.message(F.text == "👥 Администраторы")
async def admins(message: Message):

    if not await is_owner(message):
        await deny(message)
        return


    await message.answer(
        "👥 <b>Администраторы</b>",
        reply_markup=admins_menu()
    )



@router.message(F.text == "🔄 Синхронизировать LANGAME")
async def sync_admins(message: Message):

    if not await is_owner(message):
        await deny(message)
        return


    try:

        page = 1
        users = []


        while True:

            result = await langame.users(
                page=page,
                page_limit=100,
            )


            batch = (
                result.get("data")
                or result.get("items")
                or []
            )


            if not batch:
                break


            users.extend(batch)


            total_pages = result.get(
                "total_pages"
            )


            if (
                not total_pages
                or page >= int(total_pages)
            ):
                break


            page += 1



        created = 0
        updated = 0



        async with SessionLocal() as session:

            for item in users:

                if item.get("admin_status") is None:
                    continue


                langame_id = item.get("id")

                if langame_id is None:
                    continue



                employee = (
                    await session.execute(
                        select(Employee).where(
                            Employee.langame_user_id ==
                            int(langame_id)
                        )
                    )
                ).scalar_one_or_none()



                if employee is None:

                    employee = Employee(
                        langame_user_id=
                        int(langame_id)
                    )

                    session.add(employee)

                    created += 1

                else:

                    updated += 1



                employee.full_name = (
                    item.get("username")
                    or item.get("email")
                )

                employee.phone = item.get("phone")

                employee.active = bool(
                    item.get("verified")
                )



            await match_admin_profiles_to_employees(
                session
            )


            await session.commit()



        await message.answer(
            f"✅ Синхронизация завершена\n\n"
            f"Новых: {created}\n"
            f"Обновлено: {updated}"
        )



    except Exception as exc:

        await message.answer(
            f"❌ Ошибка LANGAME:\n{str(exc)[:300]}"
        )



@router.message(F.text == "⚙️ Настройки")
async def settings_menu(message: Message):

    if not await is_owner(message):
        await deny(message)
        return


    await message.answer(
        "⚙️ Настройки",
        reply_markup=owner_settings_menu()
    )



@router.message(F.text == "↩️ Назад")
async def back(message: Message):

    user = await get_access(message)

    print(
        "ACCESS DEBUG:",
        user.telegram_id if user else None,
        user.role if user else None,
        user.active if user else None
    )

    if user is None:

        await deny(message)

        return



    if user.role == UserRole.OWNER.value:

        await message.answer(
            "Главное меню",
            reply_markup=owner_menu()
        )

    else:

        await message.answer(
            "Главное меню",
            reply_markup=admin_menu()
        )