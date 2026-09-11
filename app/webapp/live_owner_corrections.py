from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Employee, Guest, GuestGroup, GuestGroupMember, Shift
from app.permissions import Permission, require_permission
from app.services.langame import LangameAPIError, langame_client
from app.services.timezone_policy import club_tz, local_day_bounds
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


def session_active(row: dict) -> bool:
    """Use explicit status fields first; LANGAME history rows can omit an end timestamp."""
    status = first(row, "status", "session_status", "state", default=None)
    if isinstance(status, dict):
        status = first(status, "name", "code", "status", default=None)
    if status is not None:
        normalized = str(status).strip().lower()
        if normalized in {"active", "opened", "open", "running", "started", "in_progress", "in progress"}:
            return True
        if normalized in {"closed", "completed", "finished", "ended", "stopped", "cancelled", "canceled"}:
            return False
    normal_stop = first(row, "normal_stop", "normalStop", default=None)
    if normal_stop is not None:
        return str(normal_stop).strip().lower() in {"0", "false", "no"}
    return not bool(session_end(row))


def row_local_date(row: dict):
    raw = first(row, "created_at", "date", "datetime", "started_at", "start_at", "timestamp", "operation_date", "paid_at", "date_start")
    if not raw:
        return None
    text = str(raw).strip()
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(club_tz()).date().isoformat()
    except Exception:
        return text[:10] if len(text) >= 10 else None


def current_local_date() -> str:
    return local_day_bounds()[0].astimezone(club_tz()).date().isoformat()


def current_day_only(rows: list[dict], day: str) -> list[dict]:
    """Defensively enforce the club-local calendar day even if upstream date filters are inclusive/wider."""
    result = []
    for row in rows:
        row_day = row_local_date(row)
        if row_day is None or row_day == day:
            result.append(row)
    return result


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
        pagination = payload.get("pagination") if isinstance(payload, dict) else None
        if total_pages is None and isinstance(pagination, dict):
            total_pages = pagination.get("total_pages") or pagination.get("last_page")
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


async def active_session_rows(start, end) -> list[dict]:
    """Prefer LANGAME's dedicated active-session endpoint; keep a safe compatibility fallback."""
    try:
        return await paged(
            langame_client.active_guest_sessions,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )
    except LangameAPIError:
        history = await paged(
            langame_client.guest_sessions,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )
        return [row for row in history if session_active(row)]


async def group_names_for(ids: set[int]) -> dict[int, str]:
    """Resolve guest groups from the local mirror first and LANGAME when the mirror is empty/stale."""
    if not ids:
        return {}
    result: dict[int, str] = {}
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Guest.langame_guest_id, GuestGroup.name)
                .join(GuestGroupMember, GuestGroupMember.guest_id == Guest.id)
                .join(GuestGroup, GuestGroup.id == GuestGroupMember.guest_group_id)
                .where(Guest.langame_guest_id.in_(list(ids)))
            )
        ).all()
    for guest_id, name in rows:
        try:
            result[int(guest_id)] = str(name)
        except (TypeError, ValueError):
            continue

    missing = set(ids) - set(result)
    if not missing:
        return result

    try:
        groups = rows_of(await langame_client.guest_groups())
    except LangameAPIError:
        return result

    async def group_members(group: dict):
        raw_group_id = first(group, "id", "group_id", "guest_group_id")
        if raw_group_id is None:
            return []
        try:
            group_id = int(raw_group_id)
        except (TypeError, ValueError):
            return []
        try:
            payload = await langame_client.guests_search(groups=[group_id], size=500, page=1)
            return [(row, str(first(group, "name", "title", default="Группа не указана"))) for row in rows_of(payload)]
        except LangameAPIError:
            return []

    batches = await asyncio.gather(*(group_members(group) for group in groups[:100]))
    for batch in batches:
        for guest, name in batch:
            raw_id = first(guest, "guest_id", "id", "guestId")
            try:
                gid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if gid in missing and gid not in result:
                result[gid] = name
    return result


async def enrich_guests(items: list[dict]) -> list[dict]:
    ids: set[int] = set()
    for item in items:
        raw_id = first(item, "guest_id", "id", "guestId")
        try:
            ids.add(int(raw_id))
        except (TypeError, ValueError):
            pass
    groups = await group_names_for(ids)
    result = []
    for item in items:
        copy = dict(item)
        raw_id = first(copy, "guest_id", "id", "guestId")
        try:
            gid = int(raw_id)
        except (TypeError, ValueError):
            gid = None
        if gid is not None and groups.get(gid):
            copy["group_name"] = groups[gid]
        elif not first(copy, "group_name", "group", "group_title"):
            copy["group_name"] = "Группа не указана"
        result.append(copy)
    return result


async def current_admins() -> list[dict]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Shift, Employee)
                .outerjoin(Employee, Employee.id == Shift.employee_id)
                .where(Shift.ended_at.is_(None))
                .order_by(Shift.started_at)
            )
        ).all()
    return [
        {
            "employee_id": shift.employee_id,
            "name": employee.full_name if employee else f"Администратор #{shift.employee_id}",
            "started_at": shift.started_at.isoformat(),
            "shift_id": shift.id,
        }
        for shift, employee in rows
    ]


@router.get("/live/overview")
async def corrected_overview(request: Request):
    await owner(request)
    start, end = local_day_bounds()
    day = start.astimezone(club_tz()).date().isoformat()
    try:
        balances, products, sessions, active_sessions, admins = await asyncio.gather(
            paged(langame_client.balances, day, day),
            paged(langame_client.product_sales, day, day),
            paged(langame_client.guest_sessions, day, day),
            active_session_rows(start, end),
            current_admins(),
        )
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME metrics unavailable: {exc}") from exc

    balances = current_day_only(balances, day)
    products = current_day_only(products, day)
    sessions = current_day_only(sessions, day)
    active_sessions = [row for row in active_sessions if session_active(row)]

    # The dashboard period is exactly the current club-local calendar day: 00:00 -> now.
    # Balance operations and product/service sales remain separate revenue streams.
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
    for row in active_sessions:
        raw_id = session_guest_id(row)
        try:
            active_ids.add(int(raw_id))
        except (TypeError, ValueError):
            continue
    for row in sessions:
        raw_id = session_guest_id(row)
        try:
            today_ids.add(int(raw_id))
        except (TypeError, ValueError):
            continue

    details = await guest_details(sorted(active_ids | today_ids))
    details = await enrich_guests(details)
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
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
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
        "current_admins": admins,
    }


@router.get("/live/guests")
async def corrected_guests(request: Request, scope: str = "today"):
    await owner(request)
    start, end = local_day_bounds()
    day = start.astimezone(club_tz()).date().isoformat()
    try:
        if scope == "active":
            sessions = await active_session_rows(start, end)
        else:
            sessions = await paged(langame_client.guest_sessions, day, day)
            sessions = current_day_only(sessions, day)
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME guests unavailable: {exc}") from exc
    ids = set()
    for row in sessions:
        raw_id = session_guest_id(row)
        try:
            gid = int(raw_id)
        except (TypeError, ValueError):
            continue
        if scope == "active" and not session_active(row):
            continue
        ids.add(gid)
    items = await guest_details(sorted(ids))
    return {
        "source": "LANGAME",
        "live": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "scope": scope,
        "items": await enrich_guests(items),
    }


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
    enriched_guest = (await enrich_guests(guests[:1]))[0] if guests else None
    sessions = []
    for row in session_rows:
        active = session_active(row)
        sessions.append({
            **row,
            "started_at": session_start(row),
            "ended_at": session_end(row),
            "active": active,
            "status_label": "Активна" if active else "Завершена",
            "club_name": first(row, "club_name", "club", "club_title", default="LANGAME"),
        })
    return {"source": "LANGAME", "live": True, "guest": enriched_guest, "sessions": sessions}
