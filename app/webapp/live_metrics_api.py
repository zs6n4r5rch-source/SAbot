from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import desc, func, select

from app.db.session import SessionLocal
from app.models import Employee, Discrepancy, Guest, SalaryPeriod, Shift, Writeoff
from app.permissions import Permission, require_permission
from app.services.langame import LangameAPIError, langame_client
from app.webapp.app import current_user

router = APIRouter(prefix="/api/app/live", tags=["live-langame"])


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


def first(row: dict, *keys: str, default=None):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def number(value: Any) -> float:
    try:
        return float(Decimal(str(value or 0)))
    except Exception:
        return 0.0


def money_value(row: dict) -> float:
    # LANGAME public API has used several names for transaction totals.
    # Prefer an explicit total/sum field; never add multiple aliases together.
    value = first(row, "amount", "sum", "total", "total_amount", "amount_total", "price", "cost")
    return number(value)


def payment_label(row: dict) -> str:
    value = first(row, "pay_system", "payment_system", "payment_method", "pay_type", "payment_type")
    if isinstance(value, dict):
        value = first(value, "name", "title", "code", "id")
    return str(value) if value not in (None, "") else "Не определено"


async def paged(method, *args, **kwargs) -> list[dict]:
    result: list[dict] = []
    page = 1
    while page <= 100:
        payload = await method(*args, page=page, page_limit=500, **kwargs)
        batch = rows_of(payload)
        if not batch:
            break
        result.extend(batch)
        total_pages = payload.get("total_pages") if isinstance(payload, dict) else None
        if total_pages is None or page >= int(total_pages):
            break
        page += 1
    return result


async def transaction_rows(start: datetime, end: datetime) -> list[dict]:
    return await paged(langame_client.transactions, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))


async def product_rows(start: datetime, end: datetime) -> list[dict]:
    return await paged(langame_client.product_sales, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))


async def session_rows(start: datetime, end: datetime) -> list[dict]:
    return await paged(langame_client.guest_sessions, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))


async def actor(request: Request):
    return (await current_user(request))[0]


def owner(user):
    require_permission(user.role, Permission.READ_ALL)


@router.get("/overview")
async def live_overview(request: Request, days: int = 1):
    user = await actor(request)
    owner(user)
    days = min(max(days, 1), 365)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    try:
        tx = await transaction_rows(start, end)
        products = await product_rows(start, end)
        sessions = await session_rows(start, end)
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME metrics unavailable: {exc}") from exc

    revenue = 0.0
    payments: dict[str, float] = {}
    for row in tx:
        if int(first(row, "cancel", "cancelled", "is_cancelled", default=0) or 0) == 1:
            continue
        amount = money_value(row)
        if amount <= 0:
            continue
        revenue += amount
        key = payment_label(row)
        payments[key] = payments.get(key, 0.0) + amount

    product_revenue = 0.0
    product_units = 0.0
    for row in products:
        if int(first(row, "cancel", "cancelled", "is_cancelled", default=0) or 0) == 1:
            continue
        qty = number(first(row, "count", "quantity", "qty", default=0))
        price = number(first(row, "price_sale", "sale_price", "price", "amount", default=0))
        product_units += qty
        product_revenue += qty * price

    unique_guests = {first(x, "guest_id", "client_id", "user_id") for x in sessions}
    unique_guests.discard(None)
    return {
        "source": "LANGAME",
        "live": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "revenue": {"total": revenue, "transactions": len(tx), "payments": payments},
        "products": {"revenue": product_revenue, "units": product_units, "sales_rows": len(products)},
        "guests": {"sessions": len(sessions), "unique": len(unique_guests)},
    }


@router.get("/analytics")
async def live_analytics(request: Request, days: int = 30):
    user = await actor(request)
    owner(user)
    days = min(max(days, 1), 365)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    try:
        tx, products, sessions = await __import__("asyncio").gather(
            transaction_rows(start, end), product_rows(start, end), session_rows(start, end)
        )
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME analytics unavailable: {exc}") from exc

    revenue = sum(max(0.0, money_value(x)) for x in tx if int(first(x, "cancel", "cancelled", "is_cancelled", default=0) or 0) != 1)
    product_revenue = sum(
        number(first(x, "count", "quantity", "qty", default=0)) * number(first(x, "price_sale", "sale_price", "price", "amount", default=0))
        for x in products if int(first(x, "cancel", "cancelled", "is_cancelled", default=0) or 0) != 1
    )
    units = sum(number(first(x, "count", "quantity", "qty", default=0)) for x in products)
    guests = {first(x, "guest_id", "client_id", "user_id") for x in sessions}
    guests.discard(None)

    async with SessionLocal() as session:
        shift_rows = (await session.execute(
            select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id)
            .where(Shift.started_at >= start, Shift.started_at <= end)
        )).all()
        writeoffs = await session.scalar(select(func.count(Writeoff.id)).where(Writeoff.created_at >= start, Writeoff.created_at <= end, Writeoff.status == "approved")) or 0
        discrepancies = await session.scalar(select(func.count(Discrepancy.id)).where(Discrepancy.created_at >= start, Discrepancy.created_at <= end)) or 0
        cash_difference = await session.scalar(select(func.coalesce(func.sum(Shift.cash_difference), 0)).where(Shift.started_at >= start, Shift.started_at <= end)) or 0
        salary_total = await session.scalar(select(func.coalesce(func.sum(SalaryPeriod.total_amount), 0)).where(SalaryPeriod.date_from <= end.date(), SalaryPeriod.date_to >= start.date())) or 0

    hours = 0.0
    ranking: dict[int, dict] = {}
    for shift, employee in shift_rows:
        if shift.ended_at and shift.ended_at > shift.started_at:
            hours += (shift.ended_at - shift.started_at).total_seconds() / 3600
        key = shift.employee_id or 0
        item = ranking.setdefault(key, {"employee_id": key, "employee": employee.full_name if employee else "Не указан", "shifts": 0, "hours": 0.0})
        item["shifts"] += 1
        if shift.ended_at and shift.ended_at > shift.started_at:
            item["hours"] += (shift.ended_at - shift.started_at).total_seconds() / 3600

    for item in ranking.values():
        item["sales_per_hour"] = revenue / item["hours"] if item["hours"] else None

    return {
        "source": "LANGAME + SAbot local control",
        "live": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "kpi": {
            "revenue": revenue,
            "product_revenue": product_revenue,
            "product_units": units,
            "transactions": len(tx),
            "guest_sessions": len(sessions),
            "unique_guests": len(guests),
            "average_check": revenue / len(tx) if tx else None,
            "revenue_per_guest": revenue / len(guests) if guests else None,
            "shifts": len(shift_rows),
            "hours": hours,
            "revenue_per_hour": revenue / hours if hours else None,
            "approved_writeoffs": int(writeoffs),
            "discrepancies": int(discrepancies),
            "cash_difference": float(cash_difference or 0),
            "salary_total": float(salary_total or 0),
        },
        "admin_ranking": sorted(ranking.values(), key=lambda x: (x["sales_per_hour"] or -1, x["shifts"]), reverse=True),
        "daily": [],
        "limitations": {"retention": None, "occupancy": None, "revenue_attribution_to_admin": "local shifts only; LANGAME transaction attribution is not assumed"},
    }


@router.get("/warehouse")
async def live_warehouse(request: Request):
    user = await actor(request)
    require_permission(user.role, Permission.MANAGE_WAREHOUSE if user.role == "owner" else Permission.WAREHOUSE)
    try:
        clubs = rows_of(await langame_client.clubs())
        products = rows_of(await langame_client.products())
        result: list[dict] = []
        for club in clubs:
            club_id = first(club, "id", "club_id", "clubId")
            if club_id is None:
                continue
            stock = await paged(langame_client.stock, int(club_id))
            for row in stock:
                nested = row.get("product") or row.get("goods") or row.get("good")
                pid = first(row, "product_id", "goods_id", "good_id")
                if pid is None and isinstance(nested, dict):
                    pid = first(nested, "id", "product_id", "goods_id", "good_id")
                name = first(row, "name", "title", "product_name", "goods_name")
                if not name and isinstance(nested, dict):
                    name = first(nested, "name", "title", "product_name", "goods_name")
                qty = first(row, "quantity", "balance", "count", "stock", "amount", default=None)
                if qty is None and isinstance(nested, dict):
                    qty = first(nested, "quantity", "balance", "count", "stock", "amount", default=0)
                result.append({"id": pid, "product": name or f"Товар #{pid}", "club_id": club_id, "club": first(club, "name", "title", default=f"Клуб #{club_id}"), "quantity": number(qty), "source": "LANGAME"})
        categories: dict[str, int] = {}
        for p in products:
            category = p.get("category") or p.get("group") or p.get("category_name") or p.get("group_name")
            if isinstance(category, dict):
                category = first(category, "name", "title")
            if category:
                categories[str(category)] = categories.get(str(category), 0) + 1
        return {"source": "LANGAME", "live": True, "as_of": datetime.now(timezone.utc).isoformat(), "items": result, "categories": [{"name": k, "products": v} for k, v in sorted(categories.items())]}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME warehouse unavailable: {exc}") from exc


@router.get("/guests/groups")
async def live_guest_groups(request: Request):
    user = await actor(request)
    require_permission(user.role, Permission.MANAGE_CRM if user.role == "owner" else Permission.GUESTS)
    try:
        groups = rows_of(await langame_client.guest_groups())
        return {"source": "LANGAME", "live": True, "as_of": datetime.now(timezone.utc).isoformat(), "items": [{"id": first(g, "id", "group_id", "guest_group_id"), "name": first(g, "name", "title", default="Без названия"), "count": first(g, "count", "guests_count", "members_count")} for g in groups]}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME guest groups unavailable: {exc}") from exc
