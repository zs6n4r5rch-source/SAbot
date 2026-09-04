import asyncio
import logging

from sqlalchemy import text

from app.db.session import engine

logger = logging.getLogger(__name__)
LOCK_KEY = 8987777573


class PollingLock:
    def __init__(self):
        self.conn = None
        self.acquired = False

    async def acquire(self):
        while True:
            self.conn = await engine.connect()
            try:
                result = await self.conn.execute(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}
                )
                self.acquired = bool(result.scalar())
                if self.acquired:
                    logger.info("Telegram polling lock acquired")
                    return
            except Exception:
                await self.conn.close()
                self.conn = None
                raise
            await self.conn.close()
            self.conn = None
            logger.warning("Another bot instance owns Telegram polling lock; waiting...")
            await asyncio.sleep(5)

    async def release(self):
        if self.conn is None:
            return
        try:
            if self.acquired:
                await self.conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                await self.conn.commit()
                logger.info("Telegram polling lock released")
        finally:
            await self.conn.close()
            self.conn = None
            self.acquired = False
