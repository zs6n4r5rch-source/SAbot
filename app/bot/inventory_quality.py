from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy import select

from app.bot.inventory import access
from app.db.session import SessionLocal
from app.models import Product, UserRole
from app.services.langame import langame_client

router = Router()
langame = langame_client


def _product_id(row: dict):
    nested = row.get("product") or row.get("goods") or {}
    return (
        row.get("product_id")
        or row.get("productId")
        or row.get("goods_id")
        or row.get("goodsId")
        or nested.get("id")
        if isinstance(nested, dict)
        else row.get("product_id") or row.get("productId") or row.get("goods_id") or row.get("goodsId")
    )


def _product_name(row: dict):
    nested = row.get("product") or row.get("goods") or {}
    return (
        row.get("name")
        or row.get("product_name")
        or row.get("productName")
        or (nested.get("name") if isinstance(nested, dict) else None)
    )


async def _names(rows: list[dict]) -> dict[int, str]:
    ids = set()
    for row in rows:
        pid = _product_id(row)
        try:
            if pid is not None:
                ids.add(int(pid))
        except (TypeError, ValueError):
            pass
    if not ids:
        return {}
    async with SessionLocal() as session:
        products = (await session.execute(
            select(Product).where(Product.langame_product_id.in_(ids))
        )).scalars().all()
    return {int(p.langame_product_id): p.name for p in products}


@router.message(F.text == "📥 Приходы")
async def arrivals_quality(message: Message):
    user = await access(message)
    if user is None:
        await message.answer("⛔ Доступ не настроен. Обратитесь к владельцу клуба.")
        return
    date_from = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        result = await langame.product_arrivals(date_from, date_to, page=1, page_limit=100)
        rows = result.get("data") or result.get("items") or []
        if not rows:
            await message.answer("📥 За последние 30 дней приходы не найдены.")
            return
        names = await _names(rows)
        lines = ["📥 Приходы LANGAME за 30 дней:"]
        for row in rows[:50]:
            pid = _product_id(row)
            try:
                pid_int = int(pid) if pid is not None else None
            except (TypeError, ValueError):
                pid_int = None
            name = _product_name(row) or (names.get(pid_int) if pid_int else None) or (f"Товар LANGAME #{pid_int}" if pid_int else "Товар без ID")
            qty = row.get("count", row.get("quantity", row.get("amount", "—")))
            date = row.get("date", row.get("created_at", ""))
            suffix = f" · {date}" if date else ""
            lines.append(f"• {name}: +{qty}{suffix}")
        await message.answer("\n".join(lines))
    except Exception as exc:
        await message.answer(f"❌ Не удалось получить приходы: {str(exc)[:400]}")


@router.message(F.text == "📈 Продажи бара и снеков")
async def sales_quality(message: Message):
    user = await access(message)
    if user is None:
        await message.answer("⛔ Доступ не настроен. Обратитесь к владельцу клуба.")
        return
    date_from = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        result = await langame.product_sales(date_from, date_to, page=1, page_limit=100)
        rows = result.get("data") or result.get("items") or []
        if not rows:
            await message.answer("📈 За последние 30 дней продажи не найдены.")
            return
        names = await _names(rows)
        lines = ["📈 Продажи LANGAME за 30 дней:"]
        for row in rows[:50]:
            pid = _product_id(row)
            try:
                pid_int = int(pid) if pid is not None else None
            except (TypeError, ValueError):
                pid_int = None
            name = _product_name(row) or (names.get(pid_int) if pid_int else None) or (f"Товар LANGAME #{pid_int}" if pid_int else "Товар без ID")
            qty = row.get("count", row.get("quantity", "—"))
            total = row.get("sum", row.get("amount", row.get("price_sale", "—")))
            lines.append(f"• {name}: {qty} шт. — {total}")
        await message.answer("\n".join(lines))
    except Exception as exc:
        await message.answer(f"❌ Не удалось получить продажи: {str(exc)[:400]}")
