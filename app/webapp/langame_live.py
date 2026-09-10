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
    nested = row.get("product") or row.get("goods") or row.get("good")
    if isinstance(nested, dict):
        value = first(row, "product_id", "goods_id", "good_id")
        if value is not None:
            return value
        return first(nested, "id", "product_id", "goods_id", "good_id")
    return first(row, "product_id", "goods_id", "good_id", "id")


def product_name(row: dict) -> str:
    nested = row.get("product") or row.get("goods") or row.get("good")
    if isinstance(nested, dict):
        return str(first(nested, "name", "title", "product_name", "goods_name", default=first(row, "name", "title", default="Без названия")))
    return str(first(row, "name", "title", "product_name", "goods_name", default="Без названия"))


def quantity(row: dict) -> float:
    nested = row.get("product") or row.get("goods") or row.get("good")
    value = first(row, "quantity", "balance", "count", "amount", "stock")
    if value is None and isinstance(nested, dict):
        value = first(nested, "quantity", "balance", "count", "amount", "stock", default=0)
    return number(value)


async def _paged_stock(club_id: int) -> list[dict]:
    result: list[dict] = []
    page = 1
    while page <= 100:
        payload = await langame_client.stock(int(club_id), page=page, page_limit=500)
        batch = rows_of(payload)
        if not batch:
            break
        result.extend(batch)
        total_pages = payload.get("total_pages") if isinstance(payload, dict) else None
        if total_pages is None or page >= int(total_pages):
            break
        page += 1
    return result


async def warehouse_items() -> dict:
    clubs_payload = await langame_client.clubs()
    clubs = rows_of(clubs_payload)
    items: list[dict] = []
    for club in clubs:
        club_id = first(club, "id", "club_id", "clubId")
        if club_id is None:
            continue
        for row in await _paged_stock(int(club_id)):
            key = product_key(row)
            if key is None:
                continue
            items.append({
                "id": key,
                "club_id": club_id,
                "club": first(club, "name", "title", default=f"Клуб #{club_id}"),
                "product": product_name(row),
                "category": first(row, "category_name", "category", default="—"),
                "quantity": quantity(row),
                "min_stock": 0,
                "critical": False,
                "source": "langame",
            })
    return {"source": "langame", "items": items}


async def warehouse_arrivals(days: int, now, start) -> dict:
    payload = await langame_client.product_arrivals(start.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"), page=1, page_limit=500)
    return {"items": rows_of(payload), "days": days, "source": "langame"}


async def warehouse_sales(days: int, now, start) -> dict:
    payload = await langame_client.product_sales(start.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"), page=1, page_limit=500)
    return {"items": rows_of(payload), "days": days, "source": "langame"}


__all__ = ["LangameAPIError", "warehouse_items", "warehouse_arrivals", "warehouse_sales"]
