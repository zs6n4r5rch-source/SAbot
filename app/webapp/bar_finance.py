from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.langame import langame_client

BAR_TERMS = (
    "бар", "снек", "напит", "drink", "beverage", "coffee", "tea", "water",
    "juice", "cola", "energy", "pizza", "burger", "hotdog", "sandwich",
    "food", "dessert", "кофе", "чай", "вода", "сок", "кола", "энергет",
    "лимонад", "пицц", "бургер", "хот-дог", "сэндвич", "десерт", "чипс",
    "шоколад", "батончик", "печень", "лед", "ice",
)
GAMING_TERMS = (
    "gaming", "game", "tariff", "hour", "rent", "pc", "vip", "computer",
    "игров", "тариф", "час", "аренд", "компьют", "зал", "пакет игры",
)


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _rows(payload: dict) -> list[dict]:
    value = payload.get("data") or payload.get("items") or payload.get("results") or []
    return value if isinstance(value, list) else []


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


def _text(row: dict, products: dict[str, dict]) -> str:
    pid = _product_id(row) or ""
    product = products.get(pid, {})
    values = [
        row.get("name"), row.get("product_name"), row.get("goods_name"), row.get("category"),
        row.get("category_name"), row.get("type"), product.get("name"), product.get("category"),
        product.get("category_name"), product.get("type"),
    ]
    return " ".join(str(v or "") for v in values).lower()


def is_bar_product(row: dict, products: dict[str, dict]) -> bool:
    text = _text(row, products)
    if any(term in text for term in GAMING_TERMS):
        return False
    return any(term in text for term in BAR_TERMS)


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


def _arrival_amount(row: dict) -> Decimal:
    qty = _qty(row)
    for key in ("price_purchase", "purchase_price", "price_arrival", "cost_price", "unit_price", "price"):
        if row.get(key) is not None:
            return _dec(row.get(key)) * qty
    for key in ("sum", "amount", "total", "cost"):
        if row.get(key) is not None:
            return _dec(row.get(key))
    return Decimal("0")


async def _product_map() -> dict[str, dict]:
    try:
        payload = await langame_client.products()
    except Exception:
        return {}
    result: dict[str, dict] = {}
    for row in _rows(payload):
        if not isinstance(row, dict):
            continue
        pid = _product_id(row)
        if pid:
            result[pid] = row
    return result


async def _all_sales(date_from: str, date_to: str) -> list[dict]:
    rows: list[dict] = []
    page = 1
    while True:
        payload = await langame_client.product_sales(date_from, date_to, page=page, page_limit=500)
        page_rows = _rows(payload)
        if not page_rows:
            break
        rows.extend(page_rows)
        total_pages = payload.get("total_pages")
        if not total_pages or page >= int(total_pages):
            break
        page += 1
    return rows


async def _all_arrivals(date_from: str, date_to: str) -> list[dict]:
    rows: list[dict] = []
    page = 1
    while True:
        payload = await langame_client.product_arrivals(date_from, date_to, page=page, page_limit=500)
        page_rows = _rows(payload)
        if not page_rows:
            break
        rows.extend(page_rows)
        total_pages = payload.get("total_pages")
        if not total_pages or page >= int(total_pages):
            break
        page += 1
    return rows


async def report(start: datetime, end: datetime) -> dict:
    date_from = start.astimezone(timezone.utc).strftime("%Y-%m-%d")
    date_to = end.astimezone(timezone.utc).strftime("%Y-%m-%d")
    products = await _product_map()
    sales_rows = await _all_sales(date_from, date_to)
    arrival_rows = await _all_arrivals(date_from, date_to)

    sales = Decimal("0")
    sales_units = Decimal("0")
    purchases = Decimal("0")
    purchase_units = Decimal("0")
    by_product: dict[str, dict[str, Any]] = {}

    for row in sales_rows:
        if not isinstance(row, dict) or row.get("cancel"):
            continue
        if not is_bar_product(row, products):
            continue
        qty = _qty(row)
        amount = _sale_amount(row)
        sales += amount
        sales_units += qty
        pid = _product_id(row) or _name(row, products)
        item = by_product.setdefault(pid, {"name": _name(row, products), "sold_units": Decimal("0"), "revenue": Decimal("0"), "purchases": Decimal("0"), "purchase_units": Decimal("0")})
        item["sold_units"] += qty
        item["revenue"] += amount

    for row in arrival_rows:
        if not isinstance(row, dict) or not is_bar_product(row, products):
            continue
        qty = _qty(row)
        amount = _arrival_amount(row)
        purchases += amount
        purchase_units += qty
        pid = _product_id(row) or _name(row, products)
        item = by_product.setdefault(pid, {"name": _name(row, products), "sold_units": Decimal("0"), "revenue": Decimal("0"), "purchases": Decimal("0"), "purchase_units": Decimal("0")})
        item["purchases"] += amount
        item["purchase_units"] += qty

    products_out = []
    for item in sorted(by_product.values(), key=lambda x: x["revenue"], reverse=True):
        products_out.append({
            "name": item["name"],
            "sold_units": float(item["sold_units"]),
            "revenue": float(item["revenue"]),
            "purchase_units": float(item["purchase_units"]),
            "purchases": float(item["purchases"]),
            "profit": float(item["revenue"] - item["purchases"]),
        })

    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "sales": float(sales),
        "sales_units": float(sales_units),
        "purchases": float(purchases),
        "purchase_units": float(purchase_units),
        "profit": float(sales - purchases),
        "products": products_out[:100],
        "source": "LANGAME products/expense + products/arrival",
        "purchase_basis": "Приходы за выбранный период",
    }
