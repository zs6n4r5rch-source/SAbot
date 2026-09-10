from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import desc, func, select

from app.db.session import SessionLocal
from app.models import (
    Employee, Inventory, InventoryBalance, InventoryItem, InventoryOperation, Product,
    ProductCategory, Shift, UserRole, Guest, GuestTelegram, GuestGroupMember,
    GuestGroup, SalaryViolation, SalaryPeriod, SalaryPayment, MarketingCampaign,
    MarketingCampaignGroup, MarketingRecipient, Writeoff, WriteoffItem, WriteoffReason,
    Discrepancy, StockSnapshot, AccessProfile, OwnerReportSettings, ShiftCloseReport,
    ShiftCloseStockItem,
)
from app.permissions import Permission, require_permission
from app.services.langame import langame_client, LangameAPIError
from app.services.timezone_policy import local_day_bounds, timezone_name
from app.webapp.app import current_user

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
        if isinstance(payload.get(key), list):
            return [x for x in payload[key] if isinstance(x, dict)]
    return []


def label(obj: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        if obj.get(key) not in (None, ""):
            return str(obj[key])
    return default


async def user_for(request: Request):
    return (await current_user(request))[0]


def need(user, permission):
    require_permission(user.role, permission)


async def sales_rows(start: datetime, end: datetime) -> list[dict]:
    result = []
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


async def product_sales_totals(start, end):
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
    user = await user_for(request)
    start, now = local_day_bounds()
    product_revenue = product_units = 0.0
    langame_status = "ok"
    try:
        product_revenue, product_units = await product_sales_totals(start, now)
    except LangameAPIError:
        langame_status = "unavailable"
    async with SessionLocal() as session:
        critical = await session.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock)) or 0
        guests = await session.scalar(select(func.count(Guest.id))) or 0
        open_shifts = await session.scalar(select(func.count(Shift.id)).where(Shift.ended_at.is_(None))) or 0
    return {"role": user.role, "timezone": timezone_name(), "revenue": {"products": product_revenue, "gaming": None, "other": None, "total": product_revenue, "product_units": product_units}, "attention": ([{"key": "critical_stock", "count": critical, "title": "Критический склад", "target": "warehouse"}] if critical else []), "kpi": {"guests": guests, "new_guests": None, "average_check": None, "open_shifts": open_shifts}, "source_status": {"langame": langame_status}}


@router.get("/summary")
async def summary_alias(request: Request):
    return await overview(request)


@router.get("/work-center")
async def work_center(request: Request):
    user = await user_for(request)
    need(user, Permission.SHIFT if user.role == "admin" else Permission.READ_ALL)
    async with SessionLocal() as session:
        open_shifts = await session.scalar(select(func.count(Shift.id)).where(Shift.ended_at.is_(None))) or 0
        critical = await session.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock)) or 0
        pending_writeoffs = await session.scalar(select(func.count(Writeoff.id)).where(Writeoff.status == "pending")) or 0
        open_discrepancies = await session.scalar(select(func.count(Discrepancy.id)).where(Discrepancy.status == "open")) or 0
    return {"role": user.role, "sections": ["hall", "guests", "finance", "warehouse", "previous_shift", "control", "penalties", "salary", "smm"], "open_shifts": open_shifts, "critical_stock": critical, "pending_writeoffs": pending_writeoffs, "open_discrepancies": open_discrepancies}


@router.get("/crm")
async def crm(request: Request, q: str = ""):
    user = await user_for(request)
    need(user, Permission.MANAGE_CRM if user.role == "owner" else Permission.GUESTS)
    try:
        return {"source": "langame", "items": rows_of(await langame_client.guests_search(query=q or None, size=100))}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME CRM unavailable: {exc}") from exc


@router.get("/crm/groups")
async def crm_groups(request: Request):
    user = await user_for(request)
    need(user, Permission.MANAGE_CRM if user.role == "owner" else Permission.GUESTS)
    try:
        return {"source": "langame", "items": [{"id": g.get("id", g.get("group_id", g.get("guest_group_id"))), "name": label(g, "name", "title", default="Без названия"), "count": g.get("count", g.get("guests_count"))} for g in rows_of(await langame_client.guest_groups())]}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME groups unavailable: {exc}") from exc


@router.get("/crm/groups/{group_id}")
async def crm_group(group_id: int, request: Request):
    data = await crm_groups(request)
    item = next((x for x in data["items"] if x["id"] == group_id), None)
    if not item:
        raise HTTPException(404, "Group not found")
    return item


@router.get("/crm/groups/{group_id}/guests")
async def crm_group_guests(group_id: int, request: Request):
    user = await user_for(request)
    need(user, Permission.MANAGE_CRM if user.role == "owner" else Permission.GUESTS)
    try:
        return {"source": "langame", "group_id": group_id, "items": rows_of(await langame_client.guests_search(groups=[group_id], size=100))}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME guests unavailable: {exc}") from exc


@router.get("/crm/guests/{guest_id}")
async def crm_guest(guest_id: int, request: Request):
    user = await user_for(request)
    need(user, Permission.MANAGE_CRM if user.role == "owner" else Permission.GUESTS)
    try:
        payload = await langame_client.guest_by_id(guest_id)
        rows = rows_of(payload)
        guest = rows[0] if rows else None
        return {"source": "langame", "guest": guest, "sessions": rows_of(await langame_client.guest_sessions(guest_id=guest_id, page_limit=500))}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME guest unavailable: {exc}") from exc


@router.get("/crm/local-links")
async def crm_local_links(request: Request):
    user = await user_for(request)
    need(user, Permission.MANAGE_CRM if user.role == "owner" else Permission.GUESTS)
    async with SessionLocal() as session:
        rows = (await session.execute(select(GuestTelegram, Guest))).all()
    return {"items": [{"guest_id": g.id, "name": g.fio, "phone": g.phone, "telegram_user_id": t.telegram_user_id, "marketing_consent": t.marketing_consent, "linked_at": t.linked_at.isoformat() if t.linked_at else None} for t, g in rows]}


@router.get("/warehouse")
async def warehouse(request: Request):
    user = await user_for(request)
    need(user, Permission.MANAGE_WAREHOUSE if user.role == "owner" else Permission.WAREHOUSE)
    async with SessionLocal() as session:
        rows = (await session.execute(select(InventoryBalance, Product, ProductCategory).join(Product, Product.id == InventoryBalance.product_id).outerjoin(ProductCategory, ProductCategory.id == Product.category_id))).all()
    return {"source": "local_control_layer", "items": [{"id": b.id, "club_id": b.club_id, "product": p.name, "category": c.name if c else "Other", "quantity": num(b.quantity), "min_stock": num(b.min_stock), "critical": bool(b.min_stock > 0 and b.quantity <= b.min_stock)} for b, p, c in rows]}


@router.get("/warehouse/categories")
async def warehouse_categories(request: Request):
    user = await user_for(request)
    need(user, Permission.MANAGE_WAREHOUSE if user.role == "owner" else Permission.WAREHOUSE)
    async with SessionLocal() as session:
        rows = (await session.execute(select(ProductCategory).where(ProductCategory.active.is_(True)).order_by(ProductCategory.name))).scalars().all()
    return {"items": [{"id": x.id, "name": x.name} for x in rows]}


@router.get("/warehouse/critical")
async def warehouse_critical(request: Request):
    data = await warehouse(request)
    return {"items": [x for x in data["items"] if x["critical"]]}


@router.get("/warehouse/sales")
async def warehouse_sales(request: Request, days: int = 30):
    user = await user_for(request)
    need(user, Permission.MANAGE_WAREHOUSE if user.role == "owner" else Permission.SALES)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=min(max(days, 1), 365))
    return {"items": await sales_rows(start, end), "days": days, "source": "langame"}


@router.get("/warehouse/arrivals")
async def warehouse_arrivals(request: Request, days: int = 30):
    user = await user_for(request)
    need(user, Permission.MANAGE_WAREHOUSE if user.role == "owner" else Permission.WAREHOUSE)
    days = min(max(days, 1), 365)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    try:
        return {"items": rows_of(await langame_client.product_arrivals(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), page=1, page_limit=500)), "days": days, "source": "langame"}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME arrivals unavailable: {exc}") from exc


@router.get("/warehouse/history")
async def warehouse_history(request: Request, limit: int = 100):
    user = await user_for(request)
    need(user, Permission.MANAGE_WAREHOUSE if user.role == "owner" else Permission.WAREHOUSE)
    async with SessionLocal() as session:
        rows = (await session.execute(select(InventoryOperation, Product).join(Product, Product.id == InventoryOperation.product_id).order_by(desc(InventoryOperation.created_at)).limit(min(max(limit, 1), 500)))).all()
    return {"items": [{"id": o.id, "club_id": o.club_id, "product": p.name, "employee_id": o.employee_id, "shift_id": o.shift_id, "type": o.operation_type, "quantity": num(o.quantity), "source": o.source, "comment": o.comment, "created_at": o.created_at.isoformat()} for o, p in rows]}


@router.get("/warehouse/writeoffs")
async def warehouse_writeoffs(request: Request, limit: int = 100):
    user = await user_for(request)
    need(user, Permission.MANAGE_WAREHOUSE if user.role == "owner" else Permission.WAREHOUSE)
    async with SessionLocal() as session:
        rows = (await session.execute(select(Writeoff, WriteoffReason).outerjoin(WriteoffReason, WriteoffReason.id == Writeoff.reason_id).order_by(desc(Writeoff.created_at)).limit(min(max(limit, 1), 300)))).all()
        items = []
        for w, reason in rows:
            products = (await session.execute(select(WriteoffItem, Product).join(Product, Product.id == WriteoffItem.product_id).where(WriteoffItem.writeoff_id == w.id))).all()
            items.append({"id": w.id, "club_id": w.club_id, "employee_id": w.employee_id, "shift_id": w.shift_id, "status": w.status, "reason": reason.name if reason else None, "comment": w.comment, "approved_at": w.approved_at.isoformat() if w.approved_at else None, "created_at": w.created_at.isoformat(), "items": [{"product": p.name, "quantity": num(i.quantity)} for i, p in products]})
    return {"items": items}


@router.get("/warehouse/inventories")
async def warehouse_inventories(request: Request, limit: int = 100):
    user = await user_for(request)
    need(user, Permission.MANAGE_WAREHOUSE if user.role == "owner" else Permission.WAREHOUSE)
    async with SessionLocal() as session:
        rows = (await session.execute(select(Inventory).order_by(desc(Inventory.started_at), desc(Inventory.id)).limit(min(max(limit, 1), 300)))).scalars().all()
        result = []
        for inv in rows:
            count = await session.scalar(select(func.count(InventoryItem.id)).where(InventoryItem.inventory_id == inv.id)) or 0
            diff = await session.scalar(select(func.count(InventoryItem.id)).where(InventoryItem.inventory_id == inv.id, InventoryItem.difference.is_not(None), InventoryItem.difference != 0)) or 0
            result.append({"id": inv.id, "club_id": inv.club_id, "created_by": inv.created_by, "status": inv.status, "started_at": inv.started_at.isoformat() if inv.started_at else None, "completed_at": inv.completed_at.isoformat() if inv.completed_at else None, "items": count, "discrepancies": diff, "comment": inv.comment})
    return {"items": result}


@router.get("/warehouse/discrepancies")
async def warehouse_discrepancies(request: Request, limit: int = 100):
    user = await user_for(request)
    need(user, Permission.MANAGE_WAREHOUSE if user.role == "owner" else Permission.WAREHOUSE)
    async with SessionLocal() as session:
        rows = (await session.execute(select(Discrepancy, Product).join(Product, Product.id == Discrepancy.product_id).order_by(desc(Discrepancy.created_at)).limit(min(max(limit, 1), 300)))).all()
    return {"items": [{"id": d.id, "club_id": d.club_id, "inventory_id": d.inventory_id, "product": p.name, "employee_id": d.employee_id, "shift_id": d.shift_id, "quantity_difference": num(d.quantity_difference), "amount_difference": num(d.amount_difference), "status": d.status, "created_at": d.created_at.isoformat()} for d, p in rows]}


@router.get("/finance")
async def unified_finance(request: Request, days: int = 30):
    user = await user_for(request)
    need(user, Permission.MANAGE_FINANCE)
    days = min(max(days, 1), 365)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    revenue, units = await product_sales_totals(start, end)
    async with SessionLocal() as session:
        cash_sales = await session.scalar(select(func.coalesce(func.sum(Shift.cash_sales), 0)).where(Shift.started_at >= start, Shift.started_at <= end)) or 0
        card_sales = await session.scalar(select(func.coalesce(func.sum(Shift.card_sales), 0)).where(Shift.started_at >= start, Shift.started_at <= end)) or 0
        mobile_sales = await session.scalar(select(func.coalesce(func.sum(Shift.mobile_sales), 0)).where(Shift.started_at >= start, Shift.started_at <= end)) or 0
        cash_difference = await session.scalar(select(func.coalesce(func.sum(Shift.cash_difference), 0)).where(Shift.started_at >= start, Shift.started_at <= end)) or 0
    return {"days": days, "revenue": {"gaming": None, "products": revenue, "other": None, "total": revenue}, "products": {"units": units, "revenue": revenue, "cogs": None, "profit": None, "margin": None}, "payments": {"cash": num(cash_sales), "card": num(card_sales), "mobile": num(mobile_sales), "cash_difference": num(cash_difference)}, "source_note": "COGS/gaming/other остаются unavailable до подтверждения полей источника."}


@router.get("/shifts")
async def shifts(request: Request):
    user = await user_for(request)
    need(user, Permission.READ_ALL if user.role == "owner" else Permission.SHIFT)
    async with SessionLocal() as session:
        rows = (await session.execute(select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).order_by(desc(Shift.started_at)).limit(100))).all()
    return {"items": [{"id": s.id, "langame_shift_id": s.langame_shift_id, "employee": e.full_name if e else None, "employee_id": s.employee_id, "started_at": s.started_at.isoformat(), "ended_at": s.ended_at.isoformat() if s.ended_at else None, "status": s.status, "system_cash": num(s.system_cash), "actual_cash": num(s.actual_cash), "cash_difference": num(s.cash_difference), "cash_sales": num(s.cash_sales), "card_sales": num(s.card_sales), "mobile_sales": num(s.mobile_sales), "collection": num(s.collection), "handover_note": s.handover_note} for s, e in rows]}


@router.get("/shifts/previous")
async def previous_shift(request: Request):
    user = await user_for(request)
    need(user, Permission.READ_ALL if user.role == "owner" else Permission.SHIFT)
    async with SessionLocal() as session:
        row = (await session.execute(select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.ended_at.is_not(None)).order_by(desc(Shift.ended_at)).limit(1))).first()
    if not row:
        return {"item": None}
    s, e = row
    return {"item": {"id": s.id, "langame_shift_id": s.langame_shift_id, "employee": e.full_name if e else None, "employee_id": s.employee_id, "started_at": s.started_at.isoformat(), "ended_at": s.ended_at.isoformat(), "system_cash": num(s.system_cash), "actual_cash": num(s.actual_cash), "cash_difference": num(s.cash_difference), "cash_sales": num(s.cash_sales), "card_sales": num(s.card_sales), "mobile_sales": num(s.mobile_sales), "collection": num(s.collection), "handover_note": s.handover_note}}


@router.get("/shifts/close-reports")
async def shift_close_reports(request: Request, limit: int = 100):
    user = await user_for(request)
    need(user, Permission.READ_ALL if user.role == "owner" else Permission.SHIFT)
    async with SessionLocal() as session:
        rows = (await session.execute(select(ShiftCloseReport).order_by(desc(ShiftCloseReport.created_at)).limit(min(max(limit, 1), 200)))).scalars().all()
    return {"items": [{"id": r.id, "shift_id": r.shift_id, "employee_id": r.employee_id, "status": r.status, "cash_expected": num(r.cash_expected), "cash_actual": num(r.cash_actual), "cash_difference": num(r.cash_difference), "cash_shortage_reason": r.cash_shortage_reason, "cash_comment": r.cash_comment, "stock_items_count": r.stock_items_count, "stock_discrepancies_count": r.stock_discrepancies_count, "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None, "cleaning_confirmed_at": r.cleaning_confirmed_at.isoformat() if r.cleaning_confirmed_at else None, "cleaning_performed_by": r.cleaning_performed_by, "cleaning_bonus_amount": num(r.cleaning_bonus_amount)} for r in rows]}


@router.get("/penalties")
async def penalties(request: Request):
    user = await user_for(request)
    async with SessionLocal() as session:
        stmt = select(SalaryViolation, Employee).join(Employee, Employee.id == SalaryViolation.employee_id).order_by(desc(SalaryViolation.created_at))
        if user.role == "admin" and user.employee_id:
            stmt = stmt.where(SalaryViolation.employee_id == user.employee_id)
        elif user.role != "owner":
            need(user, Permission.OWN_PENALTIES)
        rows = (await session.execute(stmt.limit(200))).all()
    return {"source": "SAbot NEW/local", "items": [{"id": v.id, "employee": e.full_name, "employee_id": v.employee_id, "shift_id": v.shift_id, "type": v.rule_code, "title": v.title, "amount": num(v.amount), "premium_reduction_percent": num(v.premium_reduction_percent), "dismissal_required": bool(v.dismissal_required), "comment": v.comment, "status": "charged", "created_at": v.created_at.isoformat()} for v, e in rows]}


@router.get("/salary")
async def salary(request: Request, limit: int = 100):
    user = await user_for(request)
    if user.role != "owner":
        raise HTTPException(403, "Salary access is restricted to owner")
    async with SessionLocal() as session:
        periods = (await session.execute(select(SalaryPeriod, Employee).join(Employee, Employee.id == SalaryPeriod.employee_id).order_by(desc(SalaryPeriod.date_to)).limit(min(max(limit, 1), 300)))).all()
        result = []
        for p, e in periods:
            payment = await session.scalar(select(SalaryPayment).where(SalaryPayment.salary_period_id == p.id))
            result.append({"id": p.id, "employee_id": p.employee_id, "employee": e.full_name, "date_from": p.date_from.isoformat(), "date_to": p.date_to.isoformat(), "base_amount": num(p.base_amount), "bonus_amount": num(p.bonus_amount), "total_amount": num(p.total_amount), "status": p.status, "confirmed_at": p.confirmed_at.isoformat() if p.confirmed_at else None, "paid": bool(payment), "paid_at": payment.paid_at.isoformat() if payment else None, "paid_amount": num(payment.amount) if payment else None})
    return {"items": result}


@router.get("/analytics")
async def unified_analytics(request: Request, days: int = 30):
    user = await user_for(request)
    need(user, Permission.READ_ALL)
    days = min(max(days, 1), 365)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    revenue, units = await product_sales_totals(start, end)
    async with SessionLocal() as session:
        shifts = (await session.execute(select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.started_at >= start, Shift.started_at <= end))).all()
        writeoffs = await session.scalar(select(func.count(Writeoff.id)).where(Writeoff.created_at >= start, Writeoff.created_at <= end, Writeoff.status == "approved")) or 0
        discrepancies = await session.scalar(select(func.count(Discrepancy.id)).where(Discrepancy.created_at >= start, Discrepancy.created_at <= end)) or 0
        cash_difference = await session.scalar(select(func.coalesce(func.sum(Shift.cash_difference), 0)).where(Shift.started_at >= start, Shift.started_at <= end)) or 0
        salary_total = await session.scalar(select(func.coalesce(func.sum(SalaryPeriod.total_amount), 0)).where(SalaryPeriod.date_from <= end.date(), SalaryPeriod.date_to >= start.date())) or 0
    hours = sum(((s.ended_at - s.started_at).total_seconds() / 3600 for s, _ in shifts if s.ended_at and s.ended_at > s.started_at), 0.0)
    by_employee = {}
    for s, e in shifts:
        key = s.employee_id or 0
        row = by_employee.setdefault(key, {"employee_id": key, "employee": e.full_name if e else "Не указан", "shifts": 0, "hours": 0.0})
        row["shifts"] += 1
        if s.ended_at and s.ended_at > s.started_at:
            row["hours"] += (s.ended_at - s.started_at).total_seconds() / 3600
    return {"days": days, "kpi": {"product_revenue": revenue, "product_units": units, "shifts": len(shifts), "hours": hours, "approved_writeoffs": int(writeoffs), "discrepancies": int(discrepancies), "cash_difference": num(cash_difference), "salary_total": num(salary_total)}, "comparison": {"occupancy": None, "revenue_per_hour": (revenue / hours if hours else None), "revenue_per_pc": None, "arpu": None, "retention": None}, "admins": sorted(by_employee.values(), key=lambda x: (x["shifts"], x["hours"]), reverse=True), "note": "Продажи привязаны к LANGAME; неподтверждённые метрики остаются NULL."}


@router.get("/admin/me")
async def admin_me(request: Request):
    user = await user_for(request)
    need(user, Permission.SHIFT)
    return {"employee_id": user.employee_id, "permissions": sorted(p.value for p in __import__("app.permissions", fromlist=["ROLE_PERMISSIONS"]).ROLE_PERMISSIONS["admin"])}


@router.get("/admin/profiles")
async def admin_profiles(request: Request):
    user = await user_for(request)
    need(user, Permission.READ_ALL)
    async with SessionLocal() as session:
        rows = (await session.execute(select(AccessProfile).order_by(AccessProfile.role, AccessProfile.display_name))).scalars().all()
    return {"items": [{"id": p.id, "display_name": p.display_name, "username": p.username, "role": p.role, "employee_id": p.employee_id, "active": p.active, "salary_per_shift": num(p.salary_per_shift), "cleaning_bonus_enabled": p.cleaning_bonus_enabled, "ideal_close_bonus_enabled": p.ideal_close_bonus_enabled, "cash_discipline_bonus_enabled": p.cash_discipline_bonus_enabled, "bar_bonus_enabled": p.bar_bonus_enabled, "employment_start_date": p.employment_start_date.isoformat() if p.employment_start_date else None, "notes": p.notes} for p in rows]}


@router.get("/settings")
async def settings(request: Request):
    user = await user_for(request)
    need(user, Permission.READ_ALL)
    async with SessionLocal() as session:
        row = (await session.execute(select(OwnerReportSettings).where(OwnerReportSettings.owner_telegram_id == user.telegram_id))).scalar_one_or_none()
    return {"configured": bool(row), "settings": ({"timezone": row.report_timezone, "hour": row.report_hour, "minute": row.report_minute, "enabled": row.enabled, "include_sales": row.include_sales, "include_shifts": row.include_shifts, "include_inventory": row.include_inventory, "include_discrepancies": row.include_discrepancies, "include_salary": row.include_salary, "include_clients": row.include_clients, "send_excel": row.send_excel} if row else None), "timezone": timezone_name()}


@router.get("/smm/campaigns")
async def smm_campaigns(request: Request):
    user = await user_for(request)
    need(user, Permission.CAMPAIGNS)
    async with SessionLocal() as session:
        rows = (await session.execute(select(MarketingCampaign).order_by(desc(MarketingCampaign.created_at)).limit(100))).scalars().all()
        result = []
        for x in rows:
            recipients = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == x.id)) or 0
            sent = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == x.id, MarketingRecipient.status == "sent")) or 0
            result.append({"id": x.id, "name": x.name, "message": x.message, "status": x.status, "scheduled_at": x.scheduled_at.isoformat() if x.scheduled_at else None, "created_at": x.created_at.isoformat(), "recipients": recipients, "sent": sent, "confirmed_at": x.confirmed_at.isoformat() if x.confirmed_at else None})
    return {"source": "SAbot local", "items": result, "delivery": "TO VERIFY"}


@router.get("/smm/campaigns/{campaign_id}")
async def smm_campaign(campaign_id: int, request: Request):
    user = await user_for(request)
    need(user, Permission.CAMPAIGNS)
    async with SessionLocal() as session:
        campaign = await session.get(MarketingCampaign, campaign_id)
        if not campaign:
            raise HTTPException(404, "Campaign not found")
        groups = (await session.execute(select(MarketingCampaignGroup, GuestGroup).join(GuestGroup, GuestGroup.id == MarketingCampaignGroup.guest_group_id).where(MarketingCampaignGroup.campaign_id == campaign_id))).all()
        recipients = (await session.execute(select(MarketingRecipient, Guest).join(Guest, Guest.id == MarketingRecipient.guest_id).where(MarketingRecipient.campaign_id == campaign_id).order_by(MarketingRecipient.id))).all()
    return {"campaign": {"id": campaign.id, "name": campaign.name, "message": campaign.message, "status": campaign.status, "scheduled_at": campaign.scheduled_at.isoformat() if campaign.scheduled_at else None, "created_at": campaign.created_at.isoformat()}, "groups": [{"id": g.id, "name": g.name} for _, g in groups], "recipients": [{"guest_id": g.id, "name": g.fio, "status": r.status, "sent_at": r.sent_at.isoformat() if r.sent_at else None, "error": r.error} for r, g in recipients], "delivery": "TO VERIFY"}


@router.get("/guest/me")
async def guest_me(request: Request):
    user = await user_for(request)
    need(user, Permission.OWN_PROFILE)
    async with SessionLocal() as session:
        link = (await session.execute(select(GuestTelegram, Guest).join(Guest, Guest.id == GuestTelegram.guest_id).where(GuestTelegram.telegram_user_id == user.telegram_id))).first()
        if not link:
            raise HTTPException(404, "Guest profile is not linked")
        tg, guest = link
        return {"guest": {"id": guest.id, "name": guest.fio, "phone": guest.phone, "marketing_consent": tg.marketing_consent, "linked_at": tg.linked_at.isoformat() if tg.linked_at else None}, "balance": None, "bonuses": None, "marketing_consent": tg.marketing_consent}
