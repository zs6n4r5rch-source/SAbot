import os
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import MenuButtonWebApp, WebAppInfo

from app.config import settings
from app.bot.admin_delete import router as admin_delete_router
from app.bot.inventory_quality import router as inventory_quality_router
from app.bot.menu_state import MenuStateResetMiddleware
from app.bot.owner_bonus_menu import router as owner_bonus_router
from app.bot.owner_data_menu import router as owner_data_router
from app.bot.smm import router as smm_router
from app.bot.start import router as start_router
from app.bot.handlers import router
from app.bot.shift_closing import router as shift_closing_router, shift_close_scheduler
from app.bot.restart import router as restart_router
from app.services.langame import langame_client
from app.services.staff_access import ensure_real_staff_profiles
from app.services.polling_lock import PollingLock
from app.services.telegram_webhook import router as telegram_webhook_router, setup_webhook
from app.db.session import engine, SessionLocal
from app.webapp.app import app as web_app
from app.webapp.statistics_api import router as statistics_router
from app.webapp.smm_api import router as smm_api_router
from app.webapp.social_api import router as social_api_router
from uvicorn import Config as UvicornConfig, Server as UvicornServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)


async def provision_staff():
    async with SessionLocal() as session:
        created = await ensure_real_staff_profiles(session)
        await session.commit()
        if created:
            logger.info("Provisioned %s real staff access profiles", created)


async def main():
    await provision_staff()
    bot = Bot(token=settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.middleware(MenuStateResetMiddleware())

    if settings.mini_app_url:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Strike Arena", web_app=WebAppInfo(url=settings.mini_app_url)))

    # /start is the canonical entry point and must precede legacy handlers.
    dp.include_router(start_router)
    dp.include_router(admin_delete_router)
    dp.include_router(owner_bonus_router)
    dp.include_router(owner_data_router)
    dp.include_router(smm_router)
    # These explicit menu handlers precede the legacy inventory router so
    # navigation cannot fall through into old numeric/form states.
    dp.include_router(inventory_quality_router)
    dp.include_router(router)
    dp.include_router(shift_closing_router)
    dp.include_router(restart_router)
    web_app.include_router(statistics_router)
    web_app.include_router(smm_api_router)
    web_app.include_router(social_api_router)
    web_app.include_router(telegram_webhook_router)

    webhook_mode = bool(os.getenv("RENDER_EXTERNAL_URL"))
    if webhook_mode:
        await setup_webhook(bot, dp)

    web_port = int(os.getenv("PORT", str(settings.web_port)))
    web_server = UvicornServer(UvicornConfig(web_app, host=settings.web_host, port=web_port, log_level="info"))
    web_task = asyncio.create_task(web_server.serve())

    from app.bot.daily_owner_report import daily_report_scheduler
    report_task = asyncio.create_task(daily_report_scheduler(bot))
    shift_close_task = asyncio.create_task(shift_close_scheduler(bot))
    polling_lock = PollingLock()

    try:
        logger.info("Starting Strike Arena bot (webhook=%s)...", webhook_mode)
        if webhook_mode:
            await web_task
        else:
            await polling_lock.acquire()
            await dp.start_polling(bot)
    finally:
        if not webhook_mode:
            await polling_lock.release()
        web_server.should_exit = True
        if not web_task.done():
            await web_task
        report_task.cancel(); shift_close_task.cancel()
        for task in (report_task, shift_close_task):
            try:
                await task
            except asyncio.CancelledError:
                pass
        await bot.session.close()
        await langame_client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
