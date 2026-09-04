import hashlib
import hmac
import logging
import os

from aiogram import Bot, Dispatcher, Router
from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter()

_bot: Bot | None = None
_dispatcher: Dispatcher | None = None
_secret: str = ""


def configure(bot: Bot, dispatcher: Dispatcher) -> str:
    global _bot, _dispatcher, _secret
    _bot = bot
    _dispatcher = dispatcher
    _secret = hashlib.sha256(bot.token.encode()).hexdigest()
    return _secret


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if _bot is None or _dispatcher is None:
        raise HTTPException(503, "Telegram webhook is not initialized")
    if not _secret or not hmac.compare_digest(x_telegram_bot_api_secret_token or "", _secret):
        raise HTTPException(403, "Invalid Telegram webhook secret")
    payload = await request.json()
    update = Update.model_validate(payload, context={"bot": _bot})
    await _dispatcher.feed_update(_bot, update)
    return {"ok": True}


async def setup_webhook(bot: Bot, dispatcher: Dispatcher) -> str:
    configure(bot, dispatcher)
    base_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if not base_url:
        raise RuntimeError("RENDER_EXTERNAL_URL is required for Telegram webhook mode")
    url = f"{base_url}/telegram/webhook"
    await bot.set_webhook(
        url=url,
        secret_token=_secret,
        allowed_updates=["message", "callback_query", "chat_member"],
        drop_pending_updates=False,
    )
    logger.info("Telegram webhook configured: %s", url)
    return url


async def remove_webhook(bot: Bot):
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        logger.info("Telegram webhook removed")
    except Exception:
        logger.exception("Failed to remove Telegram webhook")
