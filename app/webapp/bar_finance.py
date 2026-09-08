from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from app.services.langame import langame_client

MSK = ZoneInfo("Europe/Moscow")


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _rows(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("data", "items", "results", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _rows(value)
            if nested:
                return nested
    return []


def _product_id(row: dict) -> str | None:
    for key in ("list_goods_id", "product_id", "goods_id", "id"):
        value = row.get(key)
        if value is not None:
            return str(value)
    return None


def _name(row: dict, products: dict[str, dict]) -> str:
    value = row.get("name") or row.get("product_name") or row.get("goods_name") or row.get("title")
    if value:
        return str(value)
    product = products.get(_product_id(row) or "", {})
    return str(product.get("name") or product.get("product_name") or f"Товар #{_product_id(row) or '—'}")


def _qty(row: dict) -> Decimal:
    return _dec(row.get("count", row.get("quantity", row.get("qty", 0))))


def _sale_amount(row: dict) -> Decimal:
    qty = _qty(row)
    if row.get("price_sale") is not None:
        return _dec(row.get("price_sale")) * qty
    for key in ("sum", "amount", "total", "revenue"):
        if row.get(key) is not None:
            return _dec(row.get(key))
    return Decimal("0")


def _arrival_unit_price(row: dict) -> Decimal:
    for key in ("price_fact", "price_purchase", "purchase_price", "price_arrival", "cost_price", "unit_price", "price"):
        if row.get(key) is not None:
            return _dec(row.get(key))
    qty = _qty(row)
    if qty:
        for key in ("sum", "amount", "total", "cost"):
            if row.get(key) is not None:
                return _dec(row.get(key)) / qty
    return Decimal("0")


def _row_date(row: dict, *keys: str):
    for key in keys:
        value = row.get(key)
        if not value:
            continue
        text = str(value)
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(MSK).date()
        except ValueError:
            try:
                return datetime.strptime(text[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
    return None


async def _product_map() -> dict[str, dict]:
    try:
        payload = await langame_client.products()
    except Exception:
        return {}
    return {_product_id(row): row for row in _rows(payload) if isinstance(row, dict) and _product_id(row)}


async def _all_sales(date_from: str, date_to: str) -> list[dict]:
    rows, page = [], 1
    while page <= 50:
        payload = await langame_client.product_sales(date_from, date_to, page=page, page_limit=500)
        batch = _rows(payload)
        if not batch:
            break
        rows.extend(batch)
        total_pages = payload.get("total_pages") if isinstance(payload, dict) else None
        if not total_pages or page >= int(total_pages):
            break
        page += 1
    return rows


async def _all_arrivals(date_from: str, date_to: str) -> list[dict]:
    rows, page = [], 1
    while page <= 50:
        payload = await langame_client.product_arrivals(date_from, date_to, page=page, page_limit=500)
        batch = _rows(payload)
        if not batch:
            break
        rows.extend(batch)
        total_pages = payload.get("total_pages") if isinstance(payload, dict) else None
        if not total_pages or page >= int(total_pages):
            break
        page += 1
    return rows


async def report(start: datetime, end: datetime) -> dict:
    local_start = start.astimezone(MSK)
    local_end = end.astimezone(MSK)
    date_from = local_start.date().isoformat()
    date_to = local_end.date().isoformat()
    # Cost of goods sold must be based on the purchase cost of the exact
    # products that were sold, not on the total amount of all arrivals during
    # the selected period. Use weighted average historical purchase cost per
    # product, then multiply that unit cost by the sold quantity.
    cost_from = "2020-01-01"
    cost_to = date_to
    products = await _product_map()
    sales_rows = await _all_sales(date_from, date_to)
    arrival_rows = await _all_arrivals(cost_from, cost_to)
    sales = Decimal("0")
    sales_units = Decimal("0")
    purchase_value = Decimal("0")
    purchase_units = Decimal("0")
    by_product: dict[str, dict[str, Any]] = {}
    purchase_basis: dict[str, dict[str, Decimal]] = {}

    for row in arrival_rows:
        if not isinstance(row, dict):
            continue
        qty = _qty(row)
        if qty <= 0:
            continue
        pid = _product_id(row) or _name(row, products)
        unit_cost = _arrival_unit_price(row)
        basis = purchase_basis.setdefault(pid, {"value": Decimal("0"), "units": Decimal("0")})
        basis["value"] += unit_cost * qty
        basis["units"] += qty
        purchase_value += unit_cost * qty
        purchase_units += qty

    for row in sales_rows:
        if not isinstance(row, dict) or row.get("cancel"):
            continue
        qty = _qty(row)
        amount = _sale_amount(row)
        sales += amount
        sales_units += qty
        pid = _product_id(row) or _name(row, products)
        item = by_product.setdefault(pid, {"name": _name(row, products), "sold_units": Decimal("0"), "revenue": Decimal("0"), "purchases": Decimal("0"), "purchase_units": Decimal("0")})
        item["sold_units"] += qty
        item["revenue"] += amount
        basis = purchase_basis.get(pid)
        if basis and basis["units"] > 0:
            unit_cost = basis["value"] / basis["units"]
            item["purchases"] += unit_cost * qty
            item["purchase_units"] += qty

    products_out = [{"name": item["name"], "sold_units": float(item["sold_units"]), "revenue": float(item["revenue"]), "purchase_units": float(item["purchase_units"]), "purchases": float(item["purchases"]), "profit": float(item["revenue"] - item["purchases"])} for item in sorted(by_product.values(), key=lambda x: x["revenue"], reverse=True)]
    cogs = sum(Decimal(str(item["purchases"])) for item in by_product.values())
    return {"from": start.isoformat(), "to": end.isoformat(), "sales": float(sales), "sales_units": float(sales_units), "purchases": float(cogs), "purchase_units": float(sum(item["purchase_units"] for item in by_product.values())), "profit": float(sales - cogs), "products": products_out[:100], "source": "LANGAME products/expense + historical products/arrival", "purchase_basis": "Средневзвешенная закупочная стоимость конкретно проданных товаров"}
