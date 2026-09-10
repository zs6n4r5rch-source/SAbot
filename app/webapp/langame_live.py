from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.langame import LangameAPIError, langame_client


def rows_of(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "data", "results", "rows", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            nested = rows_of(value)
            if nested:
                return nested
    return []


def first(obj: dict, *keys: str, default=None):
    for key in keys:
        value = obj.get(key)
        if value is not None and value != "":
            return value
    return default


def number(value: Any) -> float:
    try:
        return float(Decimal(str(value or 0)))
    except Exception:
        return 0.0


def product_key(row: dict):
    return first(row, "product_id", "goods_id", "good_id", "id")


def product_name(row: dict) -> str:
    return str(first(row, "name", "title", "product_name", "goods_name", default="Без названия"))


def quantity(row: dict) -> float:
    return number(first(row, "quantity", "balance", "count", "amount", "stock", default=0))


async def warehouse_items() -> dict:
    products_payload, balances_payload = await _products_and_balances()
    products = rows_of(products_payload)
    balances = rows_of(balances_payload)
    names = {str(product_key(p)): product_name(p) for p in products if product_key(p) is not None}

    items: list[dict] = []
    for balance in balances:
        key = product_key(balance)
        if key is None:
            continue
        name = first(balance, "product_name", "goods_name", "name", default=names.get(str(key), f"Товар #{key}"))
        club_id = first(balance, "club_id", "club", "clubId")
        items.append({
            "id": key,
            "club_id": club_id,
            "product": str(name),
            "category": first(balance, "category_name", "category", default="—"),
            "quantity": quantity(balance),
            "min_stock": 0,
            "critical": False,
            "source": "langame",
        })
    return {"source": "langame", "items": items}


async def _products_and_balances():
    return await _gather_readers()


async def _gather_readers():
    # Keep the calls sequential: the shared LANGAME client is deliberately small,
    # and sequential calls make failures easier to diagnose in production logs.
    products = await langame_client.products()
    balances = await langame_client.balances(page=1, page_limit=500)
    return products, balances


async def warehouse_arrivals(days: int, now, start) -> dict:
    payload = await langame_client.product_arrivals(start.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"), page=1, page_limit=500)
    return {"items": rows_of(payload), "days": days, "source": "langame"}


async def warehouse_sales(days: int, now, start) -> dict:
    payload = await langame_client.product_sales(start.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"), page=1, page_limit=500)
    return {"items": rows_of(payload), "days": days, "source": "langame"}


__all__ = ["LangameAPIError", "warehouse_items", "warehouse_arrivals", "warehouse_sales"]
