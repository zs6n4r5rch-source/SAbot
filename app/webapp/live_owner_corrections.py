from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from app.permissions import Permission, require_permission
from app.services.langame import LangameAPIError, langame_client
from app.services.timezone_policy import local_day_bounds
from app.webapp.app import current_user

router = APIRouter(prefix="/api/app", tags=["live-owner-corrections"])


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


def money(row: dict) -> float:
    value = first(row, "amount", "sum", "total", "total_amount", "amount_total", "value", "cost")
    if isinstance(value, dict):
        value = first(value, "amount", "sum", "total", "value", default=0)
    return number(value)


def cancelled(row: dict) -> bool:
    value = first(row, "cancel", "cancelled", "is_cancelled", default=0)
    return str(value).lower() in {"1", "true", "yes"}


def session_guest_id(row: dict):
    return first(row, "guest_id", "client_id", "user_id", "guestId", "clientId")


def session_end(row: dict):
    return first(row, "ended_at", "end_at", "finished_at", "closed_at", "stop_at", "end_time", "finish_time", "finish_at", "stopped_at")


def session_start(row: dict):
    return first(row, "started_at", "start_at", "created_at", "start_time", "begin_at", "begin_time", "open_at", "opened_at", "visit_at", "session_start")


async def owner(request: Request):
    user = (await current_user(request))[0]
    require_permission(user.role, Permission.READ_ALL)
    return user


async def paged(method, *args, **kwargs) -> list[dict]:
    result: list[dict] = []
    for page in range(1, 101):
        payload = await method(*args, page=page, page_limit=500, **kwargs)
        batch = rows_of(payload)
        if not batch:
            break
        result.extend(batch)
        total_pages = payload.get("total_pages") if isinstance(payload, dict) else None
        if total_pages is not None and page >= int(total_pages):
            break
    return result


async def guest_details(ids: list[int]) -> list[dict]:
    async def one(guest_id: int):
        try:
            rows = rows_of(await langame_client.guest_by_id(guest_id))
            return rows[0] if rows else None
        except LangameAPIError:
            return None
    return [x for x in await asyncio.gather(*(one(i) for i in ids[:100])) if isinstance(x, dict)]


@router.get("/live/overview")
async def corrected_overview(request: Request):
    await owner(request)
    start, end = local_day_bounds()
    try:
        balances, products, sessions = await asyncio.gather(
            paged(langame_client.balances, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
            paged(langame_client.product_sales, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
            paged(langame_client.guest_sessions, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
        )
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME metrics unavailable: {exc}") from exc

    # LANGAME's daily Money card is composed from balance operations + product/service sales.
    # Do not sum the generic transaction log here: it also contains debits/session operations.
    account_balances = sum(money(row) for row in balances if not cancelled(row) and money(row) > 0)
    food_services = 0.0
    product_units = 0.0
    for row in products:
        if cancelled(row):
            continue
        qty = number(first(row, "count", "quantity", "qty", default=0))
        total = first(row, "total_amount", "amount_total", "total", "sum", default=None)
        price = number(first(row, "price_sale", "sale_price", "price", default=0))
        value = number(total) if total not in (None, "") else qty * price
        product_units += qty
        food_services += value

    active_ids: set[int] = set()
    today_ids: set[int] = set()
    for row in sessions:
        raw_id = session_guest_id(row)
        try:
            gid = int(raw_id)
        except (TypeError, ValueError):
            continue
        today_ids.add(gid)
        if not session_end(row):
            active_ids.add(gid)

    details = await guest_details(sorted(active_ids | today_ids))
    by_id = {}
    for guest in details:
        gid = first(guest, "guest_id", "id", "guestId")
        try:
            by_id[int(gid)] = guest
        except (TypeError, ValueError):
            pass

    return {
        "source": "LANGAME + SAbot local control",
        "live": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "days": 1,
        "revenue": {
            "total": account_balances + food_services,
            "account_balances": account_balances,
            "food_services": food_services,
            "transactions": len([x for x in balances if not cancelled(x)]),
            "payments": {},
            "product_units": product_units,
        },
        "guests": {
            "active": len(active_ids),
            "today": len(today_ids),
            "active_items": [by_id[i] for i in sorted(active_ids) if i in by_id],
            "today_items": [by_id[i] for i in sorted(today_ids) if i in by_id],
        },
    }


@router.get("/live/guests")
async def corrected_guests(request: Request, scope: str = "today"):
    await owner(request)
    start, end = local_day_bounds()
    try:
        sessions = await paged(langame_client.guest_sessions, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME guests unavailable: {exc}") from exc
    ids = set()
    for row in sessions:
        raw_id = session_guest_id(row)
        try:
            gid = int(raw_id)
        except (TypeError, ValueError):
            continue
        if scope == "active" and session_end(row):
            continue
        ids.add(gid)
    return {"source": "LANGAME", "live": True, "as_of": datetime.now(timezone.utc).isoformat(), "scope": scope, "items": await guest_details(sorted(ids))}


@router.get("/crm/guests/{guest_id}")
async def corrected_guest(guest_id: int, request: Request):
    await owner(request)
    try:
        guest_rows, session_rows = await asyncio.gather(
            langame_client.guest_by_id(guest_id),
            paged(langame_client.guest_sessions, guest_id=guest_id),
        )
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME guest unavailable: {exc}") from exc
    guests = rows_of(guest_rows)
    sessions = []
    for row in session_rows:
        sessions.append({
            **row,
            "started_at": session_start(row),
            "ended_at": session_end(row),
            "club_name": first(row, "club_name", "club", "club_title", default="LANGAME"),
        })
    return {"source": "LANGAME", "live": True, "guest": guests[0] if guests else None, "sessions": sessions}
