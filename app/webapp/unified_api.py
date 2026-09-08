from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import desc, func, select

from app.db.session import SessionLocal
from app.models import Employee, InventoryBalance, Product, Shift, TelegramUser, UserRole, Guest
from app.services.langame import langame_client, LangameAPIError
from app.webapp.app import current_user, owner_required

router = APIRouter(prefix="/api/app", tags=["unified-app"])


def num(value: Any) -> float:
    try:
        return float(Decimal(str(value or 0)))
    except Exception:
        return 0.0


def rows_of(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "items", "results", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def label(obj: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        value = obj.get(key)
        if value not in (None, ""):
            return str(value)
    return default


async def sales_rows(start: datetime, end: datetime) -> list[dict]:
    result: list[dict] = []
    page = 1
    while page <= 100:
        payload = await langame_client.product_sales(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), page=page, page_limit=500)
        batch = rows_of(payload)
        if not batch:
            break
        result.extend(batch)
        total_pages = payload.get("total_pages") if isinstance(payload, dict) else None
        if total_pages is None or page >= int(total_pages):
            break
        page += 1
    return result


async def product_sales_totals(start: datetime, end: datetime) -> tuple[float, float]:
    revenue = Decimal("0")
    units = Decimal("0")
    for row in await sales_rows(start, end):
        if int(row.get("cancel", 0) or 0) == 1:
            continue
        qty = Decimal(str(row.get("count", row.get("quantity", 0)) or 0))
        price = Decimal(str(row.get("price_sale", row.get("price", 0)) or 0))
        units += qty
        revenue += qty * price
    return float(revenue), float(units)


@router.get("/overview")
async def overview(request: Request):
    user, _ = await current_user(request)
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    product_revenue, product_units = 0.0, 0.0
    langame_status = "ok"
    try:
        product_revenue, product_units = await product_sales_totals(start, now)
        clubs_payload = await langame_client.clubs()
        clubs = rows_of(clubs_payload)
        balances = rows_of(await langame_client.balances(start.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"), page_limit=500))
        sessions = rows_of(await langame_client.guest_sessions(start.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"), page_limit=500))
        active_sessions = sum(1 for x in sessions if str(x.get("status", "")).lower() in {"active", "open", "started"})
        occupied = len(sessions) if not active_sessions else active_sessions
        club_count = len(clubs)
        balance_rows = len(balances)
    except LangameAPIError:
        langame_status = "unavailable"
        active_sessions = occupied = club_count = balance_rows = 0
    async with SessionLocal() as session:
        open_shifts = await session.scalar(select(func.count(Shift.id)).where(Shift.ended_at.is_(None))) or 0
        critical = await session.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock)) or 0
        guests = await session.scalar(select(func.count(Guest.id))) or 0
    return {
        "role": user.role,
        "club": {"status": langame_status, "active_sessions": active_sessions, "occupied": occupied, "clubs": club_count, "balance_rows": balance_rows},
        "revenue": {"products": product_revenue, "gaming": None, "other": None, "total": product_revenue, "product_units": product_units},
        "attention": [{"key": "critical_stock", "count": critical, "title": "Критический склад", "target": "warehouse"}] if critical else [],
        "kpi": {"guests": guests, "new_guests": None, "average_check": None},
        "source_note": "gaming/new guest/average check остаются NULL, если текущий подтверждённый контракт проекта не даёт достоверного поля.",
        "source_status": {"langame": langame_status, "product_sales": "confirmed_by_project_contract"},
    }


@router.get("/work-center")
async def work_center(request: Request):
    user, _ = await current_user(request)
    if user.role not in (UserRole.OWNER.value, UserRole.ADMIN.value):
        raise HTTPException(403, "Access denied")
    async with SessionLocal() as session:
        open_shifts = await session.scalar(select(func.count(Shift.id)).where(Shift.ended_at.is_(None))) or 0
        critical = await session.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock)) or 0
    groups = []
    try:
        groups = rows_of(await langame_client.guest_groups())
    except LangameAPIError:
        pass
    return {"role": user.role, "sections": ["hall", "guests", "finance", "warehouse", "previous_shift", "control"], "open_shifts": open_shifts, "critical_stock": critical, "groups": [{"id": g.get("id", g.get("group_id")), "name": label(g, "name", "title", default="Без названия"), "count": g.get("count", g.get("guests_count"))} for g in groups]}


@router.get("/crm/groups")
async def crm_groups(request: Request):
    user, _ = await current_user(request)
    if user.role not in (UserRole.OWNER.value, UserRole.ADMIN.value):
        raise HTTPException(403, "Access denied")
    try:
        groups = rows_of(await langame_client.guest_groups())
        result = []
        for g in groups:
            gid = g.get("id", g.get("group_id", g.get("guest_group_id")))
            count = g.get("count", g.get("guests_count"))
            if count is None and gid is not None:
                try:
                    count = len(rows_of(await langame_client.guests_search(groups=[int(gid)], size=100)))
                except LangameAPIError:
                    count = None
            result.append({"id": gid, "name": label(g, "name", "title", default="Без названия"), "count": count})
        return {"source": "langame", "items": result}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME groups unavailable: {exc}") from exc


@router.get("/crm/groups/{group_id}/guests")
async def crm_group_guests(group_id: int, request: Request):
    user, _ = await current_user(request)
    if user.role not in (UserRole.OWNER.value, UserRole.ADMIN.value):
        raise HTTPException(403, "Access denied")
    try:
        payload = await langame_client.guests_search(groups=[group_id], size=100)
        return {"source": "langame", "group_id": group_id, "items": rows_of(payload)}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME guests unavailable: {exc}") from exc


@router.get("/crm/guests/{guest_id}")
async def crm_guest(guest_id: int, request: Request):
    user, _ = await current_user(request)
    if user.role not in (UserRole.OWNER.value, UserRole.ADMIN.value):
        raise HTTPException(403, "Access denied")
    try:
        guest_payload = await langame_client.guest_by_id(guest_id)
        guest_rows = rows_of(guest_payload)
        guest = guest_rows[0] if guest_rows else None
        sessions = rows_of(await langame_client.guest_sessions(guest_id=guest_id, page_limit=500))
        return {"source": "langame", "guest": guest, "sessions": sessions}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME guest unavailable: {exc}") from exc


@router.get("/warehouse")
async def warehouse(request: Request):
    user, _ = await current_user(request)
    if user.role not in (UserRole.OWNER.value, UserRole.ADMIN.value):
        raise HTTPException(403, "Access denied")
    try:
        clubs = rows_of(await langame_client.clubs())
        products = rows_of(await langame_client.products())
        stocks: list[dict] = []
        for club in clubs[:20]:
            club_id = club.get("id", club.get("club_id"))
            if club_id is None:
                continue
            try:
                stock_rows = rows_of(await langame_client.stock(int(club_id)))
            except LangameAPIError:
                continue
            for row in stock_rows:
                stocks.append({**row, "club_id": club_id, "club_name": label(club, "name", "title", default=f"Клуб #{club_id}")})
        return {"source": "langame", "products": products, "items": stocks}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME warehouse unavailable: {exc}") from exc


@router.get("/finance")
async def unified_finance(request: Request, days: int = 30):
    user, _ = await current_user(request)
    owner_required(user)
    days = min(max(days, 1), 365)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    revenue, units = await product_sales_totals(start, end)
    cogs = None
    try:
        # The project contract confirms sale price/count/cancel. COGS is only returned
        # when LANGAME actually supplies a cost field on the sale line.
        cost_total = Decimal("0")
        have_cost = False
        for row in await sales_rows(start, end):
            if int(row.get("cancel", 0) or 0) == 1:
                continue
            raw_cost = row.get("cost", row.get("price_cost", row.get("purchase_price")))
            if raw_cost is None:
                continue
            have_cost = True
            cost_total += Decimal(str(raw_cost or 0)) * Decimal(str(row.get("count", row.get("quantity", 0)) or 0))
        if have_cost:
            cogs = float(cost_total)
    except Exception:
        cogs = None
    profit = revenue - cogs if cogs is not None else None
    return {"days": days, "revenue": {"gaming": None, "products": revenue, "other": None, "total": revenue}, "products": {"units": units, "revenue": revenue, "cogs": cogs, "profit": profit, "margin": (profit / revenue * 100) if profit is not None and revenue else None}, "expenses": {"salary": None, "writeoffs": None, "other": None}, "source_note": "Gaming/зарплата/прочие расходы не подменяются догадкой при отсутствии подтверждённого поля."}


@router.get("/shifts/previous")
async def previous_shift(request: Request):
    user, _ = await current_user(request)
    if user.role not in (UserRole.OWNER.value, UserRole.ADMIN.value):
        raise HTTPException(403, "Access denied")
    async with SessionLocal() as session:
        shift = (await session.execute(select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.ended_at.is_not(None)).order_by(desc(Shift.ended_at)).limit(1))).first()
    if not shift:
        return {"item": None}
    sh, emp = shift
    return {"item": {"id": sh.id, "langame_shift_id": sh.langame_shift_id, "employee": emp.full_name if emp else None, "started_at": sh.started_at.isoformat(), "ended_at": sh.ended_at.isoformat(), "cash_difference": num(sh.cash_difference)}}


@router.get("/analytics")
async def unified_analytics(request: Request, days: int = 30):
    user, _ = await current_user(request)
    owner_required(user)
    days = min(max(days, 1), 365)
    end = datetime.now(timezone.utc); start = end - timedelta(days=days)
    revenue, units = await product_sales_totals(start, end)
    async with SessionLocal() as session:
        guests = await session.scalar(select(func.count(Guest.id))) or 0
        shifts = await session.scalar(select(func.count(Shift.id)).where(Shift.started_at >= start)) or 0
    return {"days": days, "kpi": {"product_revenue": revenue, "product_units": units, "guests": guests, "shifts": shifts, "average_product_check": revenue / shifts if shifts else None}, "comparison": {"occupancy": None, "revenue_per_hour": None, "revenue_per_pc": None, "arpu": None, "retention": None, "visit_frequency": None}, "note": "Показатели без подтверждённого источника возвращаются NULL, а не рассчитываются из неподходящих прокси."}
