from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Employee, Discrepancy, InventoryBalance, Product, SalaryPeriod, Shift, Writeoff
from app.permissions import Permission, require_permission
from app.services.langame import LangameAPIError, langame_client
from app.services.timezone_policy import club_tz, local_month_bounds, local_period_bounds, local_day_bounds
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
    value = first(row, "amount", "sum", "total", "total_amount", "amount_total", "price", "cost", "value")
    if isinstance(value, dict):
        value = first(value, "amount", "sum", "total", "value", "price", default=0)
    return number(value)


def cancelled(row: dict) -> bool:
    value = first(row, "cancel", "cancelled", "is_cancelled", default=0)
    return str(value).lower() in {"1", "true", "yes"}


async def paged(method, *args, **kwargs) -> list[dict]:
    result: list[dict] = []
    for page in range(1, 101):
        payload = await method(*args, page=page, page_limit=500, **kwargs)
        batch = rows_of(payload)
        if not batch:
            break
        result.extend(batch)
        total_pages = payload.get("total_pages") if isinstance(payload, dict) else None
        if total_pages is None or page >= int(total_pages):
            break
    return result


async def transaction_rows(start: datetime, end: datetime) -> list[dict]:
    return await paged(langame_client.transactions, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))


async def product_rows(start: datetime, end: datetime) -> list[dict]:
    return await paged(langame_client.product_sales, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))


async def session_rows(start: datetime, end: datetime) -> list[dict]:
    return await paged(langame_client.guest_sessions, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))


async def guest_rows(ids: list[int]) -> list[dict]:
    async def one(guest_id: int):
        payload = await langame_client.guest_by_id(guest_id)
        rows = rows_of(payload)
        return rows[0] if rows else None
    if not ids:
        return []
    result = await asyncio.gather(*(one(i) for i in ids[:100]), return_exceptions=True)
    return [x for x in result if isinstance(x, dict)]


async def actor(request: Request):
    return (await current_user(request))[0]


def owner(user):
    require_permission(user.role, Permission.READ_ALL)


def period_bounds(days: int, period: str | None):
    if period == "month":
        return local_month_bounds()
    return local_period_bounds(days)


def row_local_date(row: dict):
    raw = first(row, "created_at", "date", "datetime", "started_at", "timestamp", "operation_date")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(club_tz()).date().isoformat()
    except Exception:
        return str(raw)[:10] if len(str(raw)) >= 10 else None


@router.get("/overview")
async def live_overview(request: Request, days: int = 1):
    user = await actor(request)
    owner(user)
    days = min(max(days, 1), 365)
    start, end = local_period_bounds(days)
    try:
        tx, products, sessions = await asyncio.gather(transaction_rows(start, end), product_rows(start, end), session_rows(start, end))
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME metrics unavailable: {exc}") from exc

    # LANGAME account-balance revenue comes from transaction rows; food/services are
    # product-expense rows. Keep the streams separate on the dashboard.
    balance_revenue = sum(money_value(row) for row in tx if not cancelled(row) and money_value(row) > 0)
    food_services_revenue = 0.0
    product_units = 0.0
    for row in products:
        if cancelled(row):
            continue
        qty = number(first(row, "count", "quantity", "qty", default=0))
        price = number(first(row, "price_sale", "sale_price", "price", "amount", default=0))
        product_units += qty
        food_services_revenue += qty * price

    today_start, _ = local_day_bounds()
    today_iso = today_start.astimezone(club_tz()).date().isoformat()
    active_ids: set[int] = set()
    today_ids: set[int] = set()
    for row in sessions:
        guest_id = first(row, "guest_id", "client_id", "user_id")
        try:
            guest_id = int(guest_id)
        except (TypeError, ValueError):
            continue
        end_value = first(row, "ended_at", "end_at", "finished_at", "closed_at", "stop_at", "end_time")
        if not end_value:
            active_ids.add(guest_id)
        if row_local_date(row) == today_iso:
            today_ids.add(guest_id)
    details = await guest_rows(sorted(active_ids | today_ids))
    by_id = {}
    for guest in details:
        gid = first(guest, "guest_id", "id")
        try:
            by_id[int(gid)] = guest
        except (TypeError, ValueError):
            pass

    async with SessionLocal() as db:
        critical = await db.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock)) or 0
        open_rows = (await db.execute(select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.ended_at.is_(None)).order_by(Shift.started_at))).all()

    current_admins = [{"employee_id": s.employee_id, "name": e.full_name if e else "Не указан", "started_at": s.started_at.isoformat(), "shift_id": s.id} for s, e in open_rows]
    total = balance_revenue + food_services_revenue
    return {
        "source": "LANGAME + SAbot local control", "live": True,
        "as_of": datetime.now(timezone.utc).isoformat(), "days": days,
        "revenue": {"total": total, "account_balances": balance_revenue, "food_services": food_services_revenue, "transactions": len([x for x in tx if not cancelled(x)]), "payments": {}, "product_units": product_units},
        "guests": {"active": len(active_ids), "today": len(today_ids), "active_items": [by_id[i] for i in sorted(active_ids) if i in by_id], "today_items": [by_id[i] for i in sorted(today_ids) if i in by_id]},
        "current_admins": current_admins,
        "attention": ([{"key": "critical_stock", "count": int(critical), "title": "Критический склад", "target": "warehouse"}] if critical else []),
    }


@router.get("/guests")
async def live_guests(request: Request, scope: str = "today"):
    user = await actor(request)
    owner(user)
    start, end = local_day_bounds()
    try:
        sessions = await session_rows(start, end)
        ids = set()
        for row in sessions:
            guest_id = first(row, "guest_id", "client_id", "user_id")
            try:
                guest_id = int(guest_id)
            except (TypeError, ValueError):
                continue
            end_value = first(row, "ended_at", "end_at", "finished_at", "closed_at", "stop_at", "end_time")
            if scope == "active" and end_value:
                continue
            ids.add(guest_id)
        return {"source": "LANGAME", "live": True, "as_of": datetime.now(timezone.utc).isoformat(), "scope": scope, "items": await guest_rows(sorted(ids))}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME guests unavailable: {exc}") from exc


@router.get("/analytics")
async def live_analytics(request: Request, days: int = 30, period: str | None = None):
    user = await actor(request)
    owner(user)
    days = min(max(days, 1), 365)
    start, end = period_bounds(days, period)
    try:
        tx, products, sessions = await asyncio.gather(transaction_rows(start, end), product_rows(start, end), session_rows(start, end))
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME analytics unavailable: {exc}") from exc
    valid_tx = [x for x in tx if not cancelled(x) and money_value(x) > 0]
    valid_products = [x for x in products if not cancelled(x)]
    revenue = sum(money_value(x) for x in valid_tx)
    units = sum(number(first(x, "count", "quantity", "qty", default=0)) for x in valid_products)
    product_revenue = sum(number(first(x, "count", "quantity", "qty", default=0)) * number(first(x, "price_sale", "sale_price", "price", "amount", default=0)) for x in valid_products)
    guests = {first(x, "guest_id", "client_id", "user_id") for x in sessions}; guests.discard(None)
    async with SessionLocal() as session:
        shift_rows = (await session.execute(select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.started_at >= start, Shift.started_at <= end))).all()
        writeoffs = await session.scalar(select(func.count(Writeoff.id)).where(Writeoff.created_at >= start, Writeoff.created_at <= end, Writeoff.status == "approved")) or 0
        discrepancies = await session.scalar(select(func.count(Discrepancy.id)).where(Discrepancy.created_at >= start, Discrepancy.created_at <= end)) or 0
        cash_difference = await session.scalar(select(func.coalesce(func.sum(Shift.cash_difference), 0)).where(Shift.started_at >= start, Shift.started_at <= end)) or 0
        salary_total = await session.scalar(select(func.coalesce(func.sum(SalaryPeriod.total_amount), 0)).where(SalaryPeriod.date_from <= end.date(), SalaryPeriod.date_to >= start.date())) or 0
    hours = 0.0; ranking: dict[int, dict] = {}; langame_shift_to_employee: dict[int, int] = {}
    for shift, employee in shift_rows:
        key = shift.employee_id or 0; item = ranking.setdefault(key, {"employee_id":key,"employee":employee.full_name if employee else "Не указан","shifts":0,"hours":0.0,"product_sales":0.0,"product_units":0.0}); item["shifts"] += 1
        if shift.langame_shift_id is not None: langame_shift_to_employee[int(shift.langame_shift_id)] = key
        if shift.ended_at and shift.ended_at > shift.started_at:
            duration=(shift.ended_at-shift.started_at).total_seconds()/3600; hours += duration; item["hours"] += duration
    for row in valid_products:
        sid=first(row,"working_shift_id","shift_id")
        try: employee_id=langame_shift_to_employee.get(int(sid))
        except (TypeError,ValueError): employee_id=None
        if employee_id is None: continue
        qty=number(first(row,"count","quantity","qty",default=0)); ranking[employee_id]["product_sales"] += qty*number(first(row,"price_sale","sale_price","price","amount",default=0)); ranking[employee_id]["product_units"] += qty
    for item in ranking.values(): item["sales_per_hour"] = item["product_sales"]/item["hours"] if item["hours"] else None
    daily: dict[str,dict] = {}
    for row in valid_tx:
        day=row_local_date(row)
        if day: daily.setdefault(day,{"date":day,"revenue":0.0,"product_revenue":0.0,"transactions":0,"sessions":0,"unique_guests":0}); daily[day]["revenue"] += money_value(row); daily[day]["transactions"] += 1
    for row in valid_products:
        day=row_local_date(row)
        if day: daily.setdefault(day,{"date":day,"revenue":0.0,"product_revenue":0.0,"transactions":0,"sessions":0,"unique_guests":0}); daily[day]["product_revenue"] += number(first(row,"count","quantity","qty",default=0))*number(first(row,"price_sale","sale_price","price","amount",default=0))
    for row in sessions:
        day=row_local_date(row)
        if day: daily.setdefault(day,{"date":day,"revenue":0.0,"product_revenue":0.0,"transactions":0,"sessions":0,"unique_guests":0}); daily[day]["sessions"] += 1
    for day in daily: daily[day]["unique_guests"] = len({first(x,"guest_id","client_id","user_id") for x in sessions if row_local_date(x)==day}-{None})
    return {"source":"LANGAME + SAbot local control","live":True,"as_of":datetime.now(timezone.utc).isoformat(),"days":days,"period":"current_month" if period=="month" else f"{days}d","kpi":{"revenue":revenue+product_revenue,"account_balances":revenue,"food_services":product_revenue,"product_revenue":product_revenue,"product_units":units,"transactions":len(valid_tx),"guest_sessions":len(sessions),"unique_guests":len(guests),"average_check":revenue/len(valid_tx) if valid_tx else None,"revenue_per_guest":revenue/len(guests) if guests else None,"shifts":len(shift_rows),"hours":hours,"revenue_per_hour":(revenue+product_revenue)/hours if hours else None,"approved_writeoffs":int(writeoffs),"discrepancies":int(discrepancies),"cash_difference":float(cash_difference or 0),"salary_total":float(salary_total or 0)},"admin_ranking":sorted(ranking.values(),key=lambda x:(x["sales_per_hour"] is not None,x["sales_per_hour"] or -1,x["shifts"]),reverse=True),"daily":list(daily.values()),"limitations":{"retention":None,"occupancy":None,"revenue_attribution_to_admin":"product sales only via LANGAME working_shift_id; unlinked revenue is not attributed"}}


@router.get("/warehouse")
async def live_warehouse(request: Request):
    user = await actor(request); require_permission(user.role, Permission.MANAGE_WAREHOUSE if user.role == "owner" else Permission.WAREHOUSE)
    try:
        clubs=rows_of(await langame_client.clubs()); products=rows_of(await langame_client.products())
        async with SessionLocal() as session: local_rows=(await session.execute(select(InventoryBalance,Product).join(Product,Product.id==InventoryBalance.product_id))).all()
        min_stock={(int(b.club_id),int(p.langame_product_id)):float(b.min_stock or 0) for b,p in local_rows if p.langame_product_id is not None}; result=[]
        for club in clubs:
            club_id=first(club,"id","club_id","clubId")
            if club_id is None: continue
            for row in await paged(langame_client.stock,int(club_id)):
                nested=row.get("product") or row.get("goods") or row.get("good"); pid=first(row,"product_id","goods_id","good_id")
                if pid is None and isinstance(nested,dict): pid=first(nested,"id","product_id","goods_id","good_id")
                name=first(row,"name","title","product_name","goods_name") or (first(nested,"name","title","product_name","goods_name") if isinstance(nested,dict) else None); qty=first(row,"quantity","balance","count","stock","amount",default=0)
                if qty is None and isinstance(nested,dict): qty=first(nested,"quantity","balance","count","stock","amount",default=0)
                q=number(qty); threshold=min_stock.get((int(club_id),int(pid))) if pid is not None else None; result.append({"id":pid,"product":name or f"Товар #{pid}","club_id":club_id,"club":first(club,"name","title",default=f"Клуб #{club_id}"),"quantity":q,"min_stock":threshold,"critical":bool(threshold is not None and threshold>0 and q<=threshold),"source":"LANGAME"})
        categories={}
        for product in products:
            category=product.get("category") or product.get("group") or product.get("category_name") or product.get("group_name")
            if isinstance(category,dict): category=first(category,"name","title")
            if category: categories[str(category)]=categories.get(str(category),0)+1
        return {"source":"LANGAME","live":True,"as_of":datetime.now(timezone.utc).isoformat(),"items":result,"categories":[{"name":k,"products":v} for k,v in sorted(categories.items())]}
    except LangameAPIError as exc: raise HTTPException(502,f"LANGAME warehouse unavailable: {exc}") from exc


@router.get("/guests/groups")
async def live_guest_groups(request: Request):
    user=await actor(request); require_permission(user.role, Permission.MANAGE_CRM if user.role=="owner" else Permission.GUESTS)
    try:
        groups=rows_of(await langame_client.guest_groups()); return {"source":"LANGAME","live":True,"as_of":datetime.now(timezone.utc).isoformat(),"items":[{"id":first(g,"id","group_id","guest_group_id"),"name":first(g,"name","title",default="Без названия"),"count":first(g,"count","guests_count","members_count")} for g in groups]}
    except LangameAPIError as exc: raise HTTPException(502,f"LANGAME guest groups unavailable: {exc}") from exc
