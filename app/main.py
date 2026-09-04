import os
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import MenuButtonWebApp, WebAppInfo

from app.config import settings

from app.bot.handlers import router
from app.bot.shift_closing import (
    router as shift_closing_router,
    shift_close_scheduler,
)
from app.bot.staff_binding import (
    router as staff_binding_router,
)

from app.services.langame import langame_client
from app.services.staff_access import ensure_real_staff_profiles

from app.db.session import engine, SessionLocal
from app.models.base import Base

from app.webapp.app import app as web_app
from uvicorn import Config as UvicornConfig, Server as UvicornServer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


async def init_database():
    """
    Создание таблиц при первом запуске.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def provision_staff():
    """
    Создание реальных владельцев и администраторов.
    """
    async with SessionLocal() as session:
        created = await ensure_real_staff_profiles(session)
        await session.commit()

        if created:
            logger.info(
                "Provisioned %s real staff access profiles",
                created,
            )


async def main():

    await init_database()

    await provision_staff()

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()

    if settings.mini_app_url:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Strike Arena",
                web_app=WebAppInfo(url=settings.mini_app_url),
            )
        )

    web_server = None
    web_task = None
    web_port = int(os.getenv("PORT", str(settings.web_port)))
    web_config = UvicornConfig(web_app, host=settings.web_host, port=web_port, log_level="info")
    web_server = UvicornServer(web_config)
    web_task = asyncio.create_task(web_server.serve())

    # Основные разделы
    dp.include_router(router)

    # Закрытие смен
    dp.include_router(
        shift_closing_router
    )



    from app.bot.daily_owner_report import daily_report_scheduler

    report_task = asyncio.create_task(
        daily_report_scheduler(bot)
    )

    shift_close_task = asyncio.create_task(
        shift_close_scheduler(bot)
    )


    try:
        logger.info(
            "Starting Strike Arena bot..."
        )

        await dp.start_polling(bot)


    finally:

        if web_server:
            web_server.should_exit = True
        if web_task:
            await web_task

        report_task.cancel()
        shift_close_task.cancel()

        try:
            await report_task
        except asyncio.CancelledError:
            pass

        try:
            await shift_close_task
        except asyncio.CancelledError:
            pass


        await bot.session.close()

        await langame_client.aclose()

        await engine.dispose()



if __name__ == "__main__":
    asyncio.run(main())